//! A small IPv4 network stack: Ethernet, ARP, IPv4, ICMP (ping both ways), UDP and a DHCP client.
//! It runs in its own kernel thread ("netd"), which owns the network card and polls it.
use crate::e1000::NIC;
use crate::sched;
use alloc::format;
use alloc::string::String;
use alloc::vec;
use alloc::vec::Vec;
use spin::Mutex;

pub type Ip = [u8; 4];
pub type Mac = [u8; 6];
const BROADCAST: Mac = [0xFF; 6];

#[derive(Clone, Default)]
pub struct Config {
    pub mac: Mac,
    pub ip: Ip,
    pub mask: Ip,
    pub gateway: Ip,
    pub dns: Ip,
    pub server: Ip,
    pub lease_s: u32,
    pub configured: bool,
}

struct Ping {
    target: Ip,
    remaining: u32,
    seq: u16,
    sent_at: u64,
    waiting: bool,
    received: u32,
    sent: u32,
}

struct Net {
    cfg: Config,
    arp: Vec<(Ip, Mac)>,
    xid: u32,
    dhcp_offer: Option<(Ip, Ip)>, // (offered address, server)
    last_dhcp: u64,
    ping: Option<Ping>,
    netd: u64,
}

static NET: Mutex<Option<Net>> = Mutex::new(None);

pub fn ip_str(ip: Ip) -> String {
    format!("{}.{}.{}.{}", ip[0], ip[1], ip[2], ip[3])
}
pub fn mac_str(m: Mac) -> String {
    format!("{:02x}:{:02x}:{:02x}:{:02x}:{:02x}:{:02x}", m[0], m[1], m[2], m[3], m[4], m[5])
}
pub fn parse_ip(s: &str) -> Option<Ip> {
    let p: Vec<u8> = s.split('.').filter_map(|x| x.parse().ok()).collect();
    (p.len() == 4 && s.split('.').count() == 4).then(|| [p[0], p[1], p[2], p[3]])
}

fn checksum(data: &[u8]) -> u16 {
    let mut sum = 0u32;
    for c in data.chunks(2) {
        sum += (c[0] as u32) << 8 | *c.get(1).unwrap_or(&0) as u32;
    }
    while sum >> 16 != 0 {
        sum = (sum & 0xFFFF) + (sum >> 16);
    }
    !(sum as u16)
}

fn send_eth(dst: Mac, ethertype: u16, payload: &[u8], src: Mac) {
    let mut f = Vec::with_capacity(14 + payload.len());
    f.extend_from_slice(&dst);
    f.extend_from_slice(&src);
    f.extend_from_slice(&ethertype.to_be_bytes());
    f.extend_from_slice(payload);
    if let Some(nic) = NIC.lock().as_mut() {
        nic.send(&f);
    }
}

fn ipv4(src: Ip, dst: Ip, proto: u8, payload: &[u8], id: u16) -> Vec<u8> {
    let total = 20 + payload.len();
    let mut h = vec![0x45, 0, (total >> 8) as u8, total as u8, (id >> 8) as u8, id as u8, 0x40, 0, 64, proto, 0, 0];
    h.extend_from_slice(&src);
    h.extend_from_slice(&dst);
    let c = checksum(&h);
    h[10] = (c >> 8) as u8;
    h[11] = c as u8;
    h.extend_from_slice(payload);
    h
}

fn udp(sport: u16, dport: u16, payload: &[u8]) -> Vec<u8> {
    let len = 8 + payload.len();
    let mut u = Vec::with_capacity(len);
    u.extend_from_slice(&sport.to_be_bytes());
    u.extend_from_slice(&dport.to_be_bytes());
    u.extend_from_slice(&(len as u16).to_be_bytes());
    u.extend_from_slice(&[0, 0]); // checksum optional over IPv4
    u.extend_from_slice(payload);
    u
}

impl Net {
    fn arp_lookup(&self, ip: Ip) -> Option<Mac> {
        self.arp.iter().find(|(i, _)| *i == ip).map(|(_, m)| *m)
    }

    fn arp_request(&self, ip: Ip) {
        let mut p = vec![0, 1, 8, 0, 6, 4, 0, 1];
        p.extend_from_slice(&self.cfg.mac);
        p.extend_from_slice(&self.cfg.ip);
        p.extend_from_slice(&[0; 6]);
        p.extend_from_slice(&ip);
        send_eth(BROADCAST, 0x0806, &p, self.cfg.mac);
    }

    /// Next hop for a destination: itself on the local subnet, otherwise the gateway.
    fn next_hop(&self, dst: Ip) -> Ip {
        let local = (0..4).all(|i| dst[i] & self.cfg.mask[i] == self.cfg.ip[i] & self.cfg.mask[i]);
        if local { dst } else { self.cfg.gateway }
    }

    fn send_ip(&mut self, dst: Ip, proto: u8, payload: &[u8]) -> bool {
        let hop = self.next_hop(dst);
        match self.arp_lookup(hop) {
            Some(mac) => {
                self.xid = self.xid.wrapping_add(1);
                send_eth(mac, 0x0800, &ipv4(self.cfg.ip, dst, proto, payload, self.xid as u16), self.cfg.mac);
                true
            }
            None => {
                self.arp_request(hop);
                false
            }
        }
    }

    fn dhcp_send(&mut self, kind: u8) {
        let mut b = vec![0u8; 240];
        b[0] = 1; // BOOTREQUEST
        b[1] = 1; // Ethernet
        b[2] = 6;
        b[4..8].copy_from_slice(&self.xid.to_be_bytes());
        b[10] = 0x80; // please broadcast the reply (we have no address yet)
        b[28..34].copy_from_slice(&self.cfg.mac);
        b[236..240].copy_from_slice(&[99, 130, 83, 99]); // magic cookie
        b.extend_from_slice(&[53, 1, kind]);
        b.extend_from_slice(&[61, 7, 1]);
        b.extend_from_slice(&self.cfg.mac);
        b.extend_from_slice(&[12, 4, b's', b't', b'o', b'a']);
        if let (3, Some((ip, server))) = (kind, self.dhcp_offer) {
            b.extend_from_slice(&[50, 4]);
            b.extend_from_slice(&ip);
            b.extend_from_slice(&[54, 4]);
            b.extend_from_slice(&server);
        }
        b.extend_from_slice(&[55, 4, 1, 3, 6, 51, 255]); // ask for mask, router, DNS, lease
        let pkt = ipv4([0; 4], [255; 4], 17, &udp(68, 67, &b), 0);
        send_eth(BROADCAST, 0x0800, &pkt, self.cfg.mac);
        self.last_dhcp = crate::sys::ticks();
    }

    fn handle_dhcp(&mut self, d: &[u8]) {
        if d.len() < 240 || d[0] != 2 || d[4..8] != self.xid.to_be_bytes() || d[236..240] != [99, 130, 83, 99] {
            return;
        }
        let yiaddr: Ip = d[16..20].try_into().unwrap();
        let (mut kind, mut mask, mut router, mut dns, mut server, mut lease) = (0, [255, 255, 255, 0], [0; 4], [0; 4], [0; 4], 0);
        let mut i = 240;
        while i + 1 < d.len() && d[i] != 255 {
            if d[i] == 0 {
                i += 1;
                continue;
            }
            let (code, len) = (d[i], d[i + 1] as usize);
            let v = &d[(i + 2).min(d.len())..(i + 2 + len).min(d.len())];
            match (code, v.len()) {
                (53, 1) => kind = v[0],
                (1, 4) => mask.copy_from_slice(v),
                (3, n) if n >= 4 => router.copy_from_slice(&v[..4]),
                (6, n) if n >= 4 => dns.copy_from_slice(&v[..4]),
                (54, 4) => server.copy_from_slice(v),
                (51, 4) => lease = u32::from_be_bytes(v.try_into().unwrap()),
                _ => {}
            }
            i += 2 + len;
        }
        match kind {
            2 if !self.cfg.configured => {
                // OFFER -> REQUEST
                crate::klog!("dhcp: offered {} by {}", ip_str(yiaddr), ip_str(server));
                self.dhcp_offer = Some((yiaddr, server));
                self.dhcp_send(3);
            }
            5 => {
                // ACK
                self.cfg = Config { mac: self.cfg.mac, ip: yiaddr, mask, gateway: router, dns, server, lease_s: lease,
                    configured: true };
                crate::klog!("dhcp: configured {} / {}, gateway {}, dns {}", ip_str(yiaddr), ip_str(mask),
                    ip_str(router), ip_str(dns));
                self.arp_request(router); // learn the gateway's address now
            }
            6 => {
                crate::klog!("dhcp: server said no (NAK) - starting again");
                self.dhcp_offer = None;
            }
            _ => {}
        }
    }

    fn handle_icmp(&mut self, src: Ip, p: &[u8]) {
        if p.len() < 8 {
            return;
        }
        match p[0] {
            8 => {
                // Echo request: answer it.
                let mut r = p.to_vec();
                r[0] = 0;
                r[2] = 0;
                r[3] = 0;
                let c = checksum(&r);
                r[2] = (c >> 8) as u8;
                r[3] = c as u8;
                self.send_ip(src, 1, &r);
            }
            0 => {
                let seq = u16::from_be_bytes([p[6], p[7]]);
                if let Some(ping) = self.ping.as_mut() {
                    if ping.waiting && ping.target == src && ping.seq == seq {
                        let ms = (crate::sys::ticks() - ping.sent_at) * 1000 / crate::interrupts::TIMER_HZ;
                        ping.waiting = false;
                        ping.received += 1;
                        say(self.netd, format!("reply from {}: seq={} time={} ms", ip_str(src), seq, ms));
                    }
                }
            }
            _ => {}
        }
    }

    fn handle(&mut self, f: &[u8]) {
        if f.len() < 14 {
            return;
        }
        let ethertype = u16::from_be_bytes([f[12], f[13]]);
        let p = &f[14..];
        match ethertype {
            0x0806 if p.len() >= 28 => {
                let op = u16::from_be_bytes([p[6], p[7]]);
                let smac: Mac = p[8..14].try_into().unwrap();
                let sip: Ip = p[14..18].try_into().unwrap();
                let tip: Ip = p[24..28].try_into().unwrap();
                if !self.arp.iter().any(|(i, _)| *i == sip) && sip != [0; 4] {
                    self.arp.push((sip, smac));
                } else if let Some(e) = self.arp.iter_mut().find(|(i, _)| *i == sip) {
                    e.1 = smac;
                }
                if op == 1 && self.cfg.configured && tip == self.cfg.ip {
                    let mut r = vec![0, 1, 8, 0, 6, 4, 0, 2];
                    r.extend_from_slice(&self.cfg.mac);
                    r.extend_from_slice(&self.cfg.ip);
                    r.extend_from_slice(&smac);
                    r.extend_from_slice(&sip);
                    send_eth(smac, 0x0806, &r, self.cfg.mac);
                }
            }
            0x0800 if p.len() >= 20 && p[0] >> 4 == 4 => {
                let ihl = (p[0] & 0xF) as usize * 4;
                let total = (u16::from_be_bytes([p[2], p[3]]) as usize).min(p.len());
                if ihl < 20 || total < ihl {
                    return;
                }
                let src: Ip = p[12..16].try_into().unwrap();
                let dst: Ip = p[16..20].try_into().unwrap();
                let body = &p[ihl..total];
                let for_us = dst == self.cfg.ip || dst == [255; 4] || !self.cfg.configured;
                if !for_us {
                    return;
                }
                match p[9] {
                    1 => self.handle_icmp(src, body),
                    17 if body.len() >= 8 => {
                        let dport = u16::from_be_bytes([body[2], body[3]]);
                        if dport == 68 {
                            self.handle_dhcp(&body[8..]);
                        }
                    }
                    _ => {}
                }
            }
            _ => {}
        }
    }

    fn ping_step(&mut self) {
        let now = crate::sys::ticks();
        let hz = crate::interrupts::TIMER_HZ;
        let Some(ping) = self.ping.as_mut() else { return };
        if ping.waiting && now - ping.sent_at >= 2 * hz {
            ping.waiting = false;
            let (seq, netd) = (ping.seq, self.netd);
            say(netd, format!("no reply (seq={})", seq));
        }
        let ping = self.ping.as_mut().unwrap();
        if !ping.waiting && (ping.sent == 0 || now - ping.sent_at >= hz) {
            if ping.remaining == 0 {
                let (sent, got, netd) = (ping.sent, ping.received, self.netd);
                self.ping = None;
                say(netd, format!("[ping done: {} sent, {} received]", sent, got));
                return;
            }
            let (target, seq) = (ping.target, ping.seq.wrapping_add(1));
            let mut icmp = vec![8, 0, 0, 0, 0x53, 0x54, (seq >> 8) as u8, seq as u8];
            icmp.extend_from_slice(b"Stoa ping payload 0123456789abcdef");
            let c = checksum(&icmp);
            icmp[2] = (c >> 8) as u8;
            icmp[3] = c as u8;
            if self.send_ip(target, 1, &icmp) {
                let ping = self.ping.as_mut().unwrap();
                ping.seq = seq;
                ping.sent += 1;
                ping.remaining -= 1;
                ping.waiting = true;
                ping.sent_at = now;
            } else if now - self.ping.as_ref().unwrap().sent_at > 3 * hz {
                let netd = self.netd;
                self.ping = None;
                say(netd, String::from("[ping: no answer to ARP - host unreachable]"));
            }
        }
    }
}

fn say(pid: u64, text: String) {
    sched::CONSOLE.lock().push_back((pid, text));
}

fn netd() {
    loop {
        let mut frames = Vec::new();
        if let Some(nic) = NIC.lock().as_mut() {
            while let Some(f) = nic.receive() {
                frames.push(f);
                if frames.len() >= 32 {
                    break;
                }
            }
        }
        {
            let mut g = NET.lock();
            if let Some(n) = g.as_mut() {
                for f in &frames {
                    n.handle(f);
                }
                let now = crate::sys::ticks();
                if !n.cfg.configured && (n.last_dhcp == 0 || now - n.last_dhcp > 3 * crate::interrupts::TIMER_HZ) {
                    n.dhcp_offer = None;
                    n.xid = n.xid.wrapping_mul(1_103_515_245).wrapping_add(12345);
                    n.dhcp_send(1); // DISCOVER
                }
                n.ping_step();
            }
        }
        sched::sleep_ms(10);
    }
}

pub fn init() {
    let Some(mac) = crate::e1000::init() else {
        crate::klog!("net: no supported network card");
        return;
    };
    let seed = crate::sys::ticks() as u32 ^ u32::from_be_bytes([mac[2], mac[3], mac[4], mac[5]]);
    *NET.lock() = Some(Net {
        cfg: Config { mac, ..Default::default() },
        arp: Vec::new(),
        xid: seed | 1,
        dhcp_offer: None,
        last_dhcp: 0,
        ping: None,
        netd: 0,
    });
    let id = sched::spawn("netd", netd);
    if let Some(n) = NET.lock().as_mut() {
        n.netd = id;
    }
}

pub fn config() -> Option<Config> {
    NET.lock().as_ref().map(|n| n.cfg.clone())
}

pub fn arp_table() -> Vec<(Ip, Mac)> {
    NET.lock().as_ref().map(|n| n.arp.clone()).unwrap_or_default()
}

pub fn stats() -> (u64, u64) {
    NIC.lock().as_ref().map(|n| (n.rx_packets, n.tx_packets)).unwrap_or((0, 0))
}

/// Start pinging `target`; replies arrive in the Terminal from the netd task (whose id is returned).
pub fn ping(target: Ip, count: u32) -> Result<u64, &'static str> {
    let mut g = NET.lock();
    let n = g.as_mut().ok_or("no network card")?;
    if !n.cfg.configured {
        return Err("no network address yet (DHCP still running)");
    }
    if n.ping.is_some() {
        return Err("a ping is already running");
    }
    n.ping = Some(Ping { target, remaining: count, seq: 0, sent_at: crate::sys::ticks(), waiting: false, received: 0,
        sent: 0 });
    Ok(n.netd)
}

pub fn renew() {
    if let Some(n) = NET.lock().as_mut() {
        n.cfg.configured = false;
        n.last_dhcp = 0;
    }
}

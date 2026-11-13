//! CMOS real-time clock.
use x86_64::instructions::port::Port;

#[derive(Clone, Copy, Default, PartialEq, Eq)]
pub struct DateTime {
    pub year: u16,
    pub month: u8,
    pub day: u8,
    pub hour: u8,
    pub minute: u8,
    pub second: u8,
}

fn read_reg(r: u8) -> u8 {
    unsafe {
        Port::<u8>::new(0x70).write(r);
        Port::<u8>::new(0x71).read()
    }
}

fn updating() -> bool {
    read_reg(0x0A) & 0x80 != 0
}

fn raw() -> [u8; 6] {
    while updating() {}
    [read_reg(0x00), read_reg(0x02), read_reg(0x04), read_reg(0x07), read_reg(0x08), read_reg(0x09)]
}

pub fn now() -> DateTime {
    // Read until two consecutive reads agree, to avoid tearing during an update.
    let mut a = raw();
    loop {
        let b = raw();
        if a == b {
            break;
        }
        a = b;
    }
    let reg_b = read_reg(0x0B);
    let bcd = reg_b & 0x04 == 0;
    let conv = |v: u8| if bcd { (v & 0x0F) + (v >> 4) * 10 } else { v };
    let pm = a[2] & 0x80 != 0;
    let mut hour = conv(a[2] & 0x7F);
    if reg_b & 0x02 == 0 {
        // 12-hour clock
        hour %= 12;
        if pm {
            hour += 12;
        }
    }
    DateTime {
        second: conv(a[0]),
        minute: conv(a[1]),
        hour,
        day: conv(a[3]),
        month: conv(a[4]),
        year: 2000 + conv(a[5]) as u16,
    }
}

pub const MONTHS: [&str; 12] = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

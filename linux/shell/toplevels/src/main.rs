//! stoa-toplevels: bridge between the compositor's window list
//! (wlr-foreign-toplevel-management) and Stoa Shell.
//!
//! stdout: one JSON object per line
//!   {"ev":"update","id":3,"app_id":"thunar","title":"Home","active":true,"minimized":false,"maximized":false}
//!   {"ev":"closed","id":3}
//! stdin: commands, one per line: "activate <id>", "minimize <id>", "close <id>", "toggle <id>"
use std::collections::HashMap;
use std::io::{BufRead, Write};
use std::os::fd::AsFd;
use std::sync::mpsc;

use wayland_client::protocol::{wl_registry, wl_seat};
use wayland_client::{Connection, Dispatch, EventQueue, Proxy, QueueHandle};
use wayland_protocols_wlr::foreign_toplevel::v1::client::{
    zwlr_foreign_toplevel_handle_v1::{self, State as TlState, ZwlrForeignToplevelHandleV1},
    zwlr_foreign_toplevel_manager_v1::{self, ZwlrForeignToplevelManagerV1},
};

#[derive(Default, Clone)]
struct Win {
    app_id: String,
    title: String,
    active: bool,
    minimized: bool,
    maximized: bool,
}

struct App {
    seat: Option<wl_seat::WlSeat>,
    manager: Option<ZwlrForeignToplevelManagerV1>,
    wins: HashMap<u32, (ZwlrForeignToplevelHandleV1, Win)>,
}

fn esc(s: &str) -> String {
    let mut o = String::with_capacity(s.len() + 2);
    for c in s.chars() {
        match c {
            '"' => o.push_str("\\\""),
            '\\' => o.push_str("\\\\"),
            '\n' => o.push_str("\\n"),
            c if (c as u32) < 0x20 => o.push_str(&format!("\\u{:04x}", c as u32)),
            c => o.push(c),
        }
    }
    o
}

fn emit(line: String) {
    let out = std::io::stdout();
    let mut l = out.lock();
    let _ = writeln!(l, "{line}");
    let _ = l.flush();
}

impl Dispatch<wl_registry::WlRegistry, ()> for App {
    fn event(st: &mut Self, reg: &wl_registry::WlRegistry, ev: wl_registry::Event, _: &(), _: &Connection, qh: &QueueHandle<Self>) {
        if let wl_registry::Event::Global { name, interface, version } = ev {
            match interface.as_str() {
                "wl_seat" if st.seat.is_none() => {
                    st.seat = Some(reg.bind::<wl_seat::WlSeat, _, _>(name, version.min(7), qh, ()));
                }
                "zwlr_foreign_toplevel_manager_v1" => {
                    st.manager = Some(reg.bind::<ZwlrForeignToplevelManagerV1, _, _>(name, version.min(3), qh, ()));
                }
                _ => {}
            }
        }
    }
}

impl Dispatch<wl_seat::WlSeat, ()> for App {
    fn event(_: &mut Self, _: &wl_seat::WlSeat, _: wl_seat::Event, _: &(), _: &Connection, _: &QueueHandle<Self>) {}
}

impl Dispatch<ZwlrForeignToplevelManagerV1, ()> for App {
    fn event(st: &mut Self, _: &ZwlrForeignToplevelManagerV1, ev: zwlr_foreign_toplevel_manager_v1::Event, _: &(), _: &Connection, _: &QueueHandle<Self>) {
        if let zwlr_foreign_toplevel_manager_v1::Event::Toplevel { toplevel } = ev {
            let id = toplevel.id().protocol_id();
            st.wins.insert(id, (toplevel, Win::default()));
        }
    }

    wayland_client::event_created_child!(App, ZwlrForeignToplevelManagerV1, [
        zwlr_foreign_toplevel_manager_v1::EVT_TOPLEVEL_OPCODE => (ZwlrForeignToplevelHandleV1, ()),
    ]);
}

impl Dispatch<ZwlrForeignToplevelHandleV1, ()> for App {
    fn event(st: &mut Self, h: &ZwlrForeignToplevelHandleV1, ev: zwlr_foreign_toplevel_handle_v1::Event, _: &(), _: &Connection, _: &QueueHandle<Self>) {
        let id = h.id().protocol_id();
        use zwlr_foreign_toplevel_handle_v1::Event as E;
        match ev {
            E::Title { title } => {
                if let Some((_, w)) = st.wins.get_mut(&id) {
                    w.title = title;
                }
            }
            E::AppId { app_id } => {
                if let Some((_, w)) = st.wins.get_mut(&id) {
                    w.app_id = app_id;
                }
            }
            E::State { state } => {
                if let Some((_, w)) = st.wins.get_mut(&id) {
                    w.active = false;
                    w.minimized = false;
                    w.maximized = false;
                    for c in state.chunks_exact(4) {
                        let v = u32::from_ne_bytes([c[0], c[1], c[2], c[3]]);
                        match TlState::try_from(v) {
                            Ok(TlState::Activated) => w.active = true,
                            Ok(TlState::Minimized) => w.minimized = true,
                            Ok(TlState::Maximized) => w.maximized = true,
                            _ => {}
                        }
                    }
                }
            }
            E::Done => {
                if let Some((_, w)) = st.wins.get(&id) {
                    emit(format!(
                        "{{\"ev\":\"update\",\"id\":{id},\"app_id\":\"{}\",\"title\":\"{}\",\"active\":{},\"minimized\":{},\"maximized\":{}}}",
                        esc(&w.app_id), esc(&w.title), w.active, w.minimized, w.maximized
                    ));
                }
            }
            E::Closed => {
                if let Some((h, _)) = st.wins.remove(&id) {
                    h.destroy();
                }
                emit(format!("{{\"ev\":\"closed\",\"id\":{id}}}"));
            }
            _ => {}
        }
    }
}

fn main() {
    let conn = Connection::connect_to_env().expect("cannot connect to the Wayland compositor");
    let mut queue: EventQueue<App> = conn.new_event_queue();
    let qh = queue.handle();
    conn.display().get_registry(&qh, ());
    let mut app = App { seat: None, manager: None, wins: HashMap::new() };
    queue.roundtrip(&mut app).expect("roundtrip");
    if app.manager.is_none() {
        eprintln!("compositor does not support zwlr_foreign_toplevel_manager_v1");
        std::process::exit(2);
    }
    emit("{\"ev\":\"ready\"}".into());

    // Commands arrive on a separate thread; the main loop polls the Wayland socket and the channel.
    let (tx, rx) = mpsc::channel::<String>();
    std::thread::spawn(move || {
        for line in std::io::stdin().lock().lines() {
            match line {
                Ok(l) => {
                    if tx.send(l).is_err() {
                        break;
                    }
                }
                Err(_) => break,
            }
        }
        std::process::exit(0); // shell went away
    });

    loop {
        queue.dispatch_pending(&mut app).expect("dispatch");
        queue.flush().ok();
        while let Ok(cmd) = rx.try_recv() {
            let mut it = cmd.split_whitespace();
            let (Some(op), Some(id)) = (it.next(), it.next().and_then(|s| s.parse::<u32>().ok())) else { continue };
            if let Some((h, w)) = app.wins.get(&id) {
                match op {
                    "activate" => {
                        if let Some(seat) = &app.seat {
                            if w.minimized {
                                h.unset_minimized();
                            }
                            h.activate(seat);
                        }
                    }
                    "minimize" => h.set_minimized(),
                    "close" => h.close(),
                    "toggle" => {
                        if w.active && !w.minimized {
                            h.set_minimized();
                        } else if let Some(seat) = &app.seat {
                            h.unset_minimized();
                            h.activate(seat);
                        }
                    }
                    "maximize" => h.set_maximized(),
                    "unmaximize" => h.unset_maximized(),
                    _ => {}
                }
            }
        }
        queue.flush().ok();
        // Wait up to 50 ms for Wayland events.
        if let Some(guard) = queue.prepare_read() {
            let fd = guard.connection_fd();
            let mut pfd = [libc_pollfd(fd.as_fd())];
            let n = poll(&mut pfd, 50);
            if n > 0 {
                let _ = guard.read();
            } else {
                drop(guard);
            }
        }
    }
}

// Minimal poll(2) binding (avoids pulling in the libc crate).
#[repr(C)]
struct PollFd {
    fd: i32,
    events: i16,
    revents: i16,
}
fn libc_pollfd(fd: std::os::fd::BorrowedFd) -> PollFd {
    use std::os::fd::AsRawFd;
    PollFd { fd: fd.as_raw_fd(), events: 1, revents: 0 }
}
extern "C" {
    #[link_name = "poll"]
    fn c_poll(fds: *mut PollFd, nfds: u64, timeout: i32) -> i32;
}
fn poll(fds: &mut [PollFd], timeout_ms: i32) -> i32 {
    unsafe { c_poll(fds.as_mut_ptr(), fds.len() as u64, timeout_ms) }
}

//! Misbehaves on purpose: reads kernel memory. The kernel ends this process and carries on.
#![no_std]
#![no_main]

use stoa::println;

fn main() -> i64 {
    println!("About to read memory that belongs to the kernel...");
    let p = 0xFFFF_8000_0000_0000u64 as *const u64;
    let v = unsafe { core::ptr::read_volatile(p) };
    println!("This line should never print ({})", v);
    0
}

stoa::entry!(main);

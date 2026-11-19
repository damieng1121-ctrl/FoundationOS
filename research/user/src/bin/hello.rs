//! The first Stoa user program: runs in ring 3, in its own address space, and talks to the kernel
//! only through system calls.
#![no_std]
#![no_main]

use stoa::println;

fn main() -> i64 {
    println!("Hello from user space!");
    println!("I'm process {} - running in ring 3 with my own memory,", stoa::getpid());
    println!("loaded from an ELF file by the Stoa kernel. Uptime: {} ms.", stoa::uptime_ms());
    0
}

stoa::entry!(main);

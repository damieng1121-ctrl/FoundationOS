//! A CPU-heavy program: counts primes while the desktop stays responsive (preemptive scheduling).
#![no_std]
#![no_main]

use stoa::println;

fn is_prime(n: u64) -> bool {
    if n < 2 {
        return false;
    }
    let mut d = 2;
    while d * d <= n {
        if n % d == 0 {
            return false;
        }
        d += 1;
    }
    true
}

fn main() -> i64 {
    let start = stoa::uptime_ms();
    let mut count = 0u64;
    let mut n = 0u64;
    for step in 1..=8u64 {
        let limit = step * 400_000;
        while n < limit {
            if is_prime(n) {
                count += 1;
            }
            n += 1;
        }
        println!("primes below {:>9}: {:>6}  ({} ms)", limit, count, stoa::uptime_ms() - start);
    }
    0
}

stoa::entry!(main);

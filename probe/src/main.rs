use std::collections::HashMap;
#[inline(never)]
fn work(n: u64) -> u64 { let mut m = HashMap::new(); for i in 0..n { *m.entry(i % 97).or_insert(0u64) += i; } m.values().sum() }
fn main() { println!("{}", work(std::env::args().count() as u64 * 100_000)); }

//! GPU inference client — a `PvEval` backed by the torch sidecar
//! (`tools/gpu_server.py`) over localhost TCP, so the net forward (~80% of
//! netval per-sim cost on CPU) runs on the GPU. OFFLINE HARVEST TOOLING ONLY:
//! not bit-identical to the CPU forward (torch GPU arithmetic), so it sits in
//! the same tier as int8 — self-play data generation and paired screening,
//! never ship gates. Native-only (std::net); the wasm build never sees this.
//!
//! Protocol (little-endian, x86 both sides): on connect the server sends
//! u32 in_dim; a request is u32 n_rows + n_rows*in_dim f32 RAW features; the
//! response is n_rows*(1+N_ACTIONS) f32 (value, then all policy logits).
//! Connections are pooled; each forward_batch takes one, so concurrent worker
//! threads each talk on their own socket.
use std::io::{Read, Write};
use std::net::TcpStream;
use std::sync::Mutex;

use crate::engine::N_ACTIONS;
use crate::feats::Enc;
use crate::valuenet::PvEval;

pub struct GpuEval {
    addr: String,
    pub in_dim: usize,
    enc: Enc,
    pool: Mutex<Vec<TcpStream>>,
}

fn f32s_as_bytes(xs: &[f32]) -> &[u8] {
    // safe on x86 (little-endian, f32 has no invalid byte patterns)
    unsafe { std::slice::from_raw_parts(xs.as_ptr() as *const u8, xs.len() * 4) }
}

fn f32s_as_bytes_mut(xs: &mut [f32]) -> &mut [u8] {
    unsafe { std::slice::from_raw_parts_mut(xs.as_mut_ptr() as *mut u8, xs.len() * 4) }
}

impl GpuEval {
    pub fn connect(addr: &str) -> std::io::Result<GpuEval> {
        let (s, in_dim) = Self::dial(addr)?;
        Ok(GpuEval {
            addr: addr.to_string(),
            in_dim,
            enc: Enc::from_in_dim(in_dim),
            pool: Mutex::new(vec![s]),
        })
    }

    fn dial(addr: &str) -> std::io::Result<(TcpStream, usize)> {
        let mut s = TcpStream::connect(addr)?;
        s.set_nodelay(true)?;
        let mut b = [0u8; 4];
        s.read_exact(&mut b)?;
        Ok((s, u32::from_le_bytes(b) as usize))
    }

    fn take_conn(&self) -> TcpStream {
        if let Some(s) = self.pool.lock().unwrap().pop() {
            return s;
        }
        let (s, in_dim) = Self::dial(&self.addr).expect("gpu server dial");
        assert_eq!(in_dim, self.in_dim, "gpu server in_dim changed mid-run");
        s
    }
}

impl PvEval for GpuEval {
    fn in_dim(&self) -> usize {
        self.in_dim
    }
    fn forward_raw(&self, raw: &[f32]) -> (f32, Vec<f32>) {
        self.forward_batch(&[raw], &[true]).pop().unwrap()
    }

    fn forward_value_raw(&self, raw: &[f32]) -> f32 {
        self.forward_batch(&[raw], &[false]).pop().unwrap().0
    }

    fn forward_batch(&self, raws: &[&[f32]], need_policy: &[bool]) -> Vec<(f32, Vec<f32>)> {
        let n = raws.len();
        if n == 0 {
            return Vec::new();
        }
        let mut conn = self.take_conn();
        let mut req = Vec::with_capacity(4 + n * self.in_dim * 4);
        req.extend_from_slice(&(n as u32).to_le_bytes());
        for r in raws {
            debug_assert_eq!(r.len(), self.in_dim);
            req.extend_from_slice(f32s_as_bytes(r));
        }
        conn.write_all(&req).expect("gpu server write");
        let mut resp = vec![0f32; n * (1 + N_ACTIONS)];
        conn.read_exact(f32s_as_bytes_mut(&mut resp)).expect("gpu server read");
        self.pool.lock().unwrap().push(conn);
        (0..n)
            .map(|i| {
                let base = i * (1 + N_ACTIONS);
                let logits = if need_policy[i] {
                    resp[base + 1..base + 1 + N_ACTIONS].to_vec()
                } else {
                    Vec::new()
                };
                (resp[base], logits)
            })
            .collect()
    }

    fn encode_state(&self, s: &crate::engine::State, seat: usize) -> Vec<f32> {
        crate::feats::encode(self.enc, s, seat)
    }
}

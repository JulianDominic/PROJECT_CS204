# Hypothesis 6: Persistent connections (Gopher-modern) outperform Gopher-original on multi-file

## Local Testing

Gopher-modern does outperform Gopher-original on multi-file tests.

**Reason:** Since Gopher-modern reuses the same TCP connection for all files, it reduces the overhead of doing the 3-way handshake to get a new file.


![Multi Object Total Time (10 files) - Local](./multi_Mixed_Local.png)

## Remote Testing

Gopher-modern does outperform Gopher-original on multi-file tests.

**Reason:** Since Gopher-modern reuses the same TCP connection for all files, it reduces the overhead of doing the 3-way handshake to get a new file.


![Multi Object Total Time (10 files) - Remote](./multi_Baseline_Remote.png)

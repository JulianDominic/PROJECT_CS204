# Hypothesis 3
## Local Testing

![Time To First Byte - Local](./ttfb_High_Latency_Local.png)
![Total Transfer Time - Local](./total_transfer_time_high_latency_local.png)
![Multi Object Total Time - Local](./multi_High_Latency_Local.png)

**For local testing**, tests were conducted under the high latency scenario. From the results http/2 has the longest TTFB and total transfer time.
- NOTE: for total transfer time, we ignore the anomalous http/3 result as it may be inaccurate due to unoptimized QUIC libraries for python
However, for the multi-object test, http/2 performed the best.


## Remote Testing

![Time To First Byte - Remote](./ttfb_Baseline_remote.png)
![Total Transfer Time - Remote](./total_transfer_time_baseline_remote.png)
![Multi Object Total Time - Remote](./multi_Baseline_remote.png)

**For remote testing**, the tests were performed with the baseline scenario, as there is no need to simulate latency. http/2 still has the longest TTFB and total transfer time for 1kb.txt file.
However, the total transfer time results for the 1mb.txt file is quite random, which could be due to various factors like network congestion/queuing, packet loss and retransmission. All these factors can be very unpredictable when transmitting over the real internet.
In the multi-object test, http/2 still retains its title for the best performance. 

**In conclusion**, the hypothesis is supported for single object requests, but does not hold for multi object requests.

This is likely due to http/2 allowing the server to push unrequested objects to the client, and also interleave the transmission of different objects, mitigating any head of line blocking by large objects. This results in decreased delay for multi-object http requests for http/2, mitigating any penalty from latency.
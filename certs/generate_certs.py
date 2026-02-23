"""
Generate self-signed TLS certificates for HTTP/2 and HTTP/3 benchmarking.

These certificates are for LOCAL TESTING ONLY — not for production use.
Both HTTP/2 (ALPN h2) and HTTP/3 (QUIC + TLS 1.3) require TLS.
"""

import datetime
import ipaddress
import os
import sys

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, ec


def generate_self_signed_cert(output_dir=None):
    """Generate a self-signed certificate and EC private key for localhost."""
    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(__file__))

    os.makedirs(output_dir, exist_ok=True)

    # Use EC key (faster TLS handshakes, required by some QUIC implementations)
    key = ec.generate_private_key(ec.SECP256R1())

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "CS204 Protocol Benchmark"),
    ])

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
        .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
            ]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    # Write private key
    key_path = os.path.join(output_dir, "key.pem")
    with open(key_path, "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))

    # Write certificate
    cert_path = os.path.join(output_dir, "cert.pem")
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    print(f"Certificate generated:")
    print(f"  cert: {cert_path}")
    print(f"  key:  {key_path}")
    return cert_path, key_path


if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else None
    generate_self_signed_cert(output)

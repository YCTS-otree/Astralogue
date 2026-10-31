"""Verified HTTPS with Windows' public certificate stores, including local CAs."""
import ssl
import urllib.request


def verified_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    if hasattr(ssl, "enum_certificates"):
        for store in ("ROOT", "CA"):
            for certificate, encoding, trust in ssl.enum_certificates(store):
                if encoding == "x509_asn" and (trust is True or ssl.Purpose.SERVER_AUTH.oid in trust):
                    context.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(certificate))
    return context


def verified_opener(proxy: str | None = None):
    handlers = [urllib.request.HTTPSHandler(context=verified_context())]
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    return urllib.request.build_opener(*handlers)

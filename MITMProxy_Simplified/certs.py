import time
import OpenSSL
import ipaddress
import typing
import os
import ssl
import sys
import datetime

from pyasn1.type import univ, constraint, char, namedtype, tag
from pyasn1.codec.der.decoder import decode
from pyasn1.error import PyAsn1Error

from MITMProxy_Simplified import serializable
# Set a default expiry time
DEFAULT_EXP = 94608000  # 24 * 60 * 60 * 365 * 3 = 3 years

#  Generated with "Openssl dhparam". too slow to generate on start up

DEFAULT_DHPARAM = b"""
-----BEGIN DH PARAMETERS-----
MIICCAKCAgEAyT6LzpwVFS3gryIo29J5icvgxCnCebcdSe/NHMkD8dKJf8suFCg3
O2+dguLakSVif/t6dhImxInJk230HmfC8q93hdcg/j8rLGJYDKu3ik6H//BAHKIv
j5O9yjU3rXCfmVJQic2Nne39sg3CreAepEts2TvYHhVv3TEAzEqCtOuTjgDv0ntJ
Gwpj+BJBRQGG9NvprX1YGJ7WOFBP/hWU7d6tgvE6Xa7T/u9QIKpYHMIkcN/l3ZFB
chZEqVlyrcngtSXCROTPcDOQ6Q8QzhaBJS+Z6rcsd7X+haiQqvoFcmaJ08Ks6LQC
ZIL2EtYJw8V8z7C0igVEBIADZBI6OTbuuhDwRw//zU1uq52Oc48CIZlGxTYG/Evq
o9EWAXUYVzWkDSTeBH1r4z/qLPE2cnhtMxbFxuvK53jGB0emy2y1Ei6IhKshJ5qX
IB/aE7SSHyQ3MDHHkCmQJCsOd4Mo26YX61NZ+n501XjqpCBQ2+DfZCBh8Va2wDyv
A2Ryg9SUz8j0AXViRNMJgJrr446yro/FuJZwnQcO3WQnXeqSBnURqKjmqkeFP+d8
6mk2tqJaY507lRNqtGlLnj7f5RNoBFJDCLBNurVgfvq9TCVWKDIFD4vZRjCrnl6I
rD693XKIHUCWOjMh1if6omGXKHH40QuME2gNa50+YPn1iYDl88uDbbMCAQI=
-----END DH PARAMETERS-----
"""


def create_ca(o, cn, exp):
    """

    :param o: Organization
    :param cn: Common Names
    :param exp: Expiration Time
    :return:
    """
    key = OpenSSL.crypto.PKey()
    key.generate_key(OpenSSL.crypto.TYPE_RSA, 2048)
    cert = OpenSSL.crypto.X509()
    cert.set_serial_number(int(time.time()) * 10000)
    cert.set_version(2)
    cert.get_subject().CN = cn
    cert.get_subject().O = o
    cert.gmtime_adj_notBefore(-3600 * 48)
    cert.gmtime_adj_notAfter(exp)
    cert.set_issuer(cert.get_subject())
    cert.set_pubkey(key)
    cert.add_extensions([
        OpenSSL.crypto.X509Extension(
            b"basicConstraints",
            True,
            b"CA:TRUE"
        ),
        OpenSSL.crypto.X509Extension(
            b"nsCertType",
            False,
            b"sslCA"
        ),
        OpenSSL.crypto.X509Extension(
            b"extendedKeyUsage",
            False,
            b"serverAuth,clientAuth,emailProtection,timeStamping,msCodeInd,msCodeCom,msCTLSign,msSGC,msEFS,nsSGC"
        ),
        OpenSSL.crypto.X509Extension(
            b"keyUsage",
            True,
            b"keyCertSign, cRLSign"
        ),
        OpenSSL.crypto.X509Extension(
            b"subjectKeyIdentifier",
            False,
            b"hash",
            subject=cert
        ),
    ])
    cert.sign(key, "sha256")
    return key, cert


def dummy_cert(privkey, cacert, commonname, sans):
    """
    Generate Self-signed certificate
    :param privkey: CA private key, see create_ca
    :param cacert: CA certificate, the pubkey of the CA which will be used to decrypt the cert
    to get pubkey of the requested server
    :param commonname: Common name for the generated certificate
    :param sans: A list of Subject Alternate Names

    :return: cert if operation succeeded, None if not
    """
    """
    Basic process of generating cert:
    CA(Certificate Authority) encrypt the pubkey of a server and some other information (o, cn,
    timestamp, issuer, e.t.c) with its privkey, thus, generates a certificate for the
    server.
    
    The client, once receiving the data packet encrypted with privkey of the server and the certificate issued
    by the CA, will check if the CA is trusted, if it is, the client will use the public key of the ca to decrypt
    the certificate, deriving the public key of the server, which the client will use to decrypt the encrypted
    data packet
    
    """
    ss = []
    for i in sans:
        try:
            ipaddress.ip_address(i.decode("ascii"))
        except ValueError:
            # It is a DNS Server
            ss.append(b"DNS: %s" % i)
        else:
            ss.append(b"IP: %s" % i)
    ss = b", ".join(ss)

    cert = OpenSSL.crypto.X509()
    cert.gmtime_adj_notBefore(-3600 * 48)
    cert.gmtime_adj_notAfter(DEFAULT_EXP)
    cert.set_issuer(cacert.get_subject())
    if commonname is not None and len(commonname) < 64:
        #  A valid CN available
        cert.get_subject().CN = commonname
    cert.set_serial_number(int(time.time() * 10000))

    if ss:
        cert.set_version(2)
        cert.add_extensions(
            [OpenSSL.crypto.X509Extension(b"subjectAltName", False, ss)])
    cert.set_pubkey(cacert.get_pubkey())
    cert.sign(privkey, "sha256")
    return SSLCert(cert)


class CertStoreEntry:

    def __init__(self, cert, privatekey, chain_file):
        self.cert = cert
        self.privatekey = privatekey
        self.chain_file = chain_file


TCustomCertId = bytes  # manually provided certs
TGeneratedCertID = typing.Tuple[typing.Optional[bytes], typing.Tuple[bytes, ...]]  # (common_name. tuple(sans))
TCertId = typing.Union[TCustomCertId, TGeneratedCertID]


class CertStore:
    """
     In-memory certificate store
    """
    STORE_CAP = 100

    def __init__(
            self,
            default_privatekey,
            defalut_ca,
            default_chain_file,
            dhparams):
        self.default_privatekey = default_privatekey
        self.default_ca = defalut_ca
        self.default_chain_file = default_chain_file
        self.certs = {}  # type: typing.Dict[TCertId, CertStoreEntry]
        self.expire_queue = []

    def expire(self, entry):
        # Can only save 100 cert-key pairs. if there is more than 100,
        # Delete LRU one
        self.expire_queue.append(entry)
        if len(self.expire_queue) > self.STORE_CAP:
            d = self.expire_queue.pop(0)
            for k, v in list(self.certs.items()):
                if v == d:
                    del self.certs[k]

    @staticmethod
    def load_dhparam(path):
        if not os.path.exists(path):
            with open(path, "wb") as f:
                f.write(DEFAULT_DHPARAM)

        bio = OpenSSL.SSL._lib.BIO_new_file(path.encode(sys.getfilesystemencoding()), b"r")
        if bio != OpenSSL.SSL._ffi.NULL:
            bio = OpenSSL.SSL._ffi.gc(bio, OpenSSL.SSL._lib.BIO_free)
            dh = OpenSSL.SSL._lib.PEM_read_bio_DHparams(
                bio,
                OpenSSL.SSL._ffi.NULL,
                OpenSSL.SSL._ffi.NULL,
                OpenSSL.SSL._ffi.NULL)
            dh = OpenSSL.SSL._ffi.gc(dh, OpenSSL.SSL._lib.DH_free)
            return dh

    @classmethod
    def from_store(cls, path, basename):
        #  load a cert/key pair from the store
        ca_path = os.path.join(path, basename + "-ca.pem")
        if not os.path.exists(ca_path):
            key, ca = cls.create_store(path, basename)
        else:
            with open(ca_path, "rb") as f:
                raw = f.read()
                ca = OpenSSL.crypto.load_certificate(
                    OpenSSL.crypto.FILETYPE_PEM,
                    raw
                )
                key = OpenSSL.crypto.load_privatekey(
                    OpenSSL.crypto.FILETYPE_PEM,
                    raw
                )
        dh_path = os.path.join(path, basename + "-dhparam.pem")
        dh = cls.load_dhparam(dh_path)
        return cls(key, ca, ca_path, dh)

    @staticmethod
    def create_store(path, basename, o=None, cn=None, expiry=DEFAULT_EXP):
        if not os.path.exists(path):
            os.mkdir(path)
        o = o or basename
        cn = cn or basename

        key, ca = create_ca(o=o, cn=cn, exp=expiry)
        #  Dump CA and private key
        with open(os.path.join(path, basename + "-ca.pem"), "wb") as f:
            f.write(
                OpenSSL.crypto.dump_certificate(
                    OpenSSL.crypto.FILETYPE_PEM,
                    ca
                ))
            f.write(
                OpenSSL.crypto.dump_privatekey(
                    OpenSSL.crypto.FILETYPE_PEM,
                    key
                ))

        # Dump cert in PEM format
        with open(os.path.join(path, basename + "-ca-cert.pem"), "wb") as f:
            f.write(
                OpenSSL.crypto.dump_certificate(
                    OpenSSL.crypto.FILETYPE_PEM,
                    ca
                ))
        # Create a .cer file for android
        with open(os.path.join(path, basename + "-ca-cert.cer"), "wb") as f:
            f.write(
                OpenSSL.crypto.dump_certificate(
                    OpenSSL.crypto.FILETYPE_PEM,
                    ca
                ))

        #  Create a .p12 file for Windows devices
        with open(os.path.join(path, basename + "-ca-cert.p12"), "wb") as f:
            p12 = OpenSSL.crypto.PKCS12()
            p12.set_certificate(ca)
            f.write(p12.export())

        #  Dump the certificate and key in a PKCS12 format for Windows devices
        with open(os.path.join(path, basename + "-ca.p12"), "wb") as f:
            p12 = OpenSSL.crypto.PKCS12()
            p12.set_certificate(ca)
            p12.set_privatekey(key)
            f.write(p12.export())
        with open(os.path.join(path, basename + "-dhparam.pem"), "wb") as f:
            f.write(DEFAULT_DHPARAM)
        return key, ca

    def add_cert_file(self, spec: str, path: str) -> None:
        with open(path, "rb") as f:
            raw = f.read()
        cert = SSLCert(
            OpenSSL.crypto.load_certificate(
                OpenSSL.crypto.FILETYPE_PEM,
                raw
            ))
        try:
            privatekey = OpenSSL.crypto.load_privatekey(
                OpenSSL.crypto.FILETYPE_PEM,
                raw)
        except Exception:
            privatekey = self.default_privatekey
        self.add_cert(
            CertStoreEntry(cert, privatekey, path), spec.encode("idna")
        )

    def add_cert(self, entry: CertStoreEntry, *names: bytes):
        """
        Add a cert to the certstore, register the CN in the cert plus any SANs
        also the list of names provided as an argument
        """
        if entry.cert.cn:
            self.certs[entry.cert.cn] = entry
        for i in entry.cert.altnames:
            self.certs[i] = entry
        for i in names:
            self.certs[i] = entry

    @staticmethod
    def asterisk_forms(dn: bytes) -> typing.List[bytes]:
        """
        Return all asterisk forms for a domain. For example, for www.example.com this will return
        [b"www.example.com", b"*.example.com", b"*.com"]. The single wildcard "*" is omitted.
        """
        parts = dn.split(b".")
        ret = [dn]
        for i in range(1, len(parts)):
            ret.append(b"*." + b".".join(parts[i:]))
        return ret

    def get_cert(self, commonname: typing.Optional[bytes], sans: typing.Optional[bytes]):
        """
            Returns an (cert, privkey, cert_chain) tuple.

            commonname: Common name for the generated certificate. Must be a
            valid, plain-ASCII, IDNA-encoded domain name.

            sans: A list of Subject Alternate Names.
        """
        potential_keys = []  # type: typing.List[TCertId]
        if commonname:
            potential_keys.extend(self.asterisk_forms(commonname))
        for s in sans:
            potential_keys.extend(self.asterisk_forms(s))
        potential_keys.append(b"*")
        potential_keys.append((commonname, tuple(sans)))

        name = next(
            filter(lambda key: key in self.certs, potential_keys), None)
        if name:
            entry = self.certs[name]
        else:
            entry = CertStoreEntry(
                cert=dummy_cert(self.default_privatekey,
                                self.default_ca,
                                commonname,
                                sans),
                privatekey=self.default_privatekey,
                chain_file=self.default_chain_file
            )
        self.certs[(commonname, tuple(sans))] = entry
        self.expire(entry)
        return entry.cert, entry.privatekey, entry.chain_file


class _GeneralName(univ.Choice):
    # We only care about dNSName and iPAddress
    componentType = namedtype.NamedTypes(
        namedtype.NamedType('dNSName', char.IA5String().subtype(
            implicitTag=tag.Tag(tag.tagClassContext, tag.tagFormatSimple, 2)
        )),
        namedtype.NamedType('iPAddress', univ.OctetString().subtype(
            implicitTag=tag.Tag(tag.tagClassContext, tag.tagFormatSimple, 7)
        )),
    )


class _GeneralNames(univ.SequenceOf):
    componentType = _GeneralName()
    sizeSpec = univ.SequenceOf.sizeSpec + \
        constraint.ValueSizeConstraint(1, 1024)


class SSLCert(serializable.Serializable):

    def __init__(self, cert):
        """
            Returns a (common name, [subject alternative names]) tuple.
        """
        self.x509 = cert

    def __eq__(self, other):
        return self.digest("sha256") == other.digest("sha256")

    def get_state(self):
        return self.to_pem()

    def set_state(self, state):
        self.x509 = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM, state)

    @classmethod
    def from_state(cls, state):
        return cls.from_pem(state)

    @classmethod
    def from_pem(cls, txt):
        x509 = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM, txt)
        return cls(x509)

    @classmethod
    def from_der(cls, der):
        pem = ssl.DER_cert_to_PEM_cert(der)
        return cls.from_pem(pem)

    def to_pem(self):
        return OpenSSL.crypto.dump_certificate(
            OpenSSL.crypto.FILETYPE_PEM,
            self.x509)

    def digest(self, name):
        return self.x509.digest(name)

    @property
    def issuer(self):
        return self.x509.get_issuer().get_components()

    @property
    def notbefore(self):
        t = self.x509.get_notBefore()
        return datetime.datetime.strptime(t.decode("ascii"), "%Y%m%d%H%M%SZ")

    @property
    def notafter(self):
        t = self.x509.get_notAfter()
        return datetime.datetime.strptime(t.decode("ascii"), "%Y%m%d%H%M%SZ")

    @property
    def has_expired(self):
        return self.x509.has_expired()

    @property
    def subject(self):
        return self.x509.get_subject().get_components()

    @property
    def serial(self):
        return self.x509.get_serial_number()

    @property
    def keyinfo(self):
        pk = self.x509.get_pubkey()
        types = {
            OpenSSL.crypto.TYPE_RSA: "RSA",
            OpenSSL.crypto.TYPE_DSA: "DSA",
        }
        return (
            types.get(pk.type(), "UNKNOWN"),
            pk.bits()
        )

    @property
    def cn(self):
        c = None
        for i in self.subject:
            if i[0] == b"CN":
                c = i[1]
        return c

    @property
    def altnames(self):
        """
        Returns:
            All DNS altnames.
        """
        # tcp.TCPClient.convert_to_ssl assumes that this property only contains DNS altnames for hostname verification.
        altnames = []
        for i in range(self.x509.get_extension_count()):
            ext = self.x509.get_extension(i)
            if ext.get_short_name() == b"subjectAltName":
                try:
                    dec = decode(ext.get_data(), asn1Spec=_GeneralNames())
                except PyAsn1Error:
                    continue
                for i in dec[0]:
                    if i[0].hasValue():
                        e = i[0].asOctets()
                        altnames.append(e)

        return altnames

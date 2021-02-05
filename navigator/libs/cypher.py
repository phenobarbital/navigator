import base64
import codecs
import sys
from typing import Any, Callable, List, Literal

from Crypto import Random
from Crypto.Cipher import AES
from rncryptor import DecryptionError, RNCryptor

base64encoded = False


class Cipher(object):
    """Can Encode/Decode a string using AES-256 or RNCryptor."""

    key: str = ""
    type: str = "AES"
    iv: str = ""
    BS: int = 16
    cipher: Any = None

    def __init__(self, key: str, type: str = "AES"):
        self.key = key
        self.type = type
        if type == "AES":
            self.iv = Random.new().read(AES.block_size)
            self.cipher = AES.new(self.key, AES.MODE_CFB, self.iv)
        elif type == "RNC":
            self.cipher = RNCryptor()
        else:
            sys.exit("Not implemented")

    def encode(self, message: Any) -> str:
        if self.type == "AES":
            msg = self.iv + self.cipher.encrypt(message.encode("utf-8"))
        elif self.type == "RNC":
            msg = self.cipher.encrypt(message, self.key)
            if base64encoded:
                msg = base64.b64encode(msg)
        else:
            return ""
        if msg:
            return codecs.encode(msg, "hex").decode("utf-8")
        else:
            return ""

    def decode(self, passphrase: Any) -> bytes:
        msg = codecs.decode(passphrase, "hex")
        if self.type == "AES":
            try:
                return self.cipher.decrypt(msg)[len(self.iv) :].decode("utf-8")
            except Exception as e:
                print(e)
                raise (e)
        elif self.type == "RNC":
            try:
                msg = self.cipher.decrypt(msg, self.key)
                if base64encoded:
                    return base64.b64decode(msg, validate=True)
                else:
                    return msg
            except DecryptionError:
                raise ValueError("Error decoding message")
            except Exception as e:
                print(e)
                raise (e)
        else:
            return b""

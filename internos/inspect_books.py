"""Source fingerprint and lossless ligature normalization."""
import hashlib

LIGATURES = str.maketrans({'ﬀ':'ff','ﬁ':'fi','ﬂ':'fl','ﬃ':'ffi','ﬄ':'ffl','ﬅ':'st','ﬆ':'st'})

def fingerprint(path):
    with open(path,'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def clean(text):
    return ''.join(text.translate(LIGATURES).split())

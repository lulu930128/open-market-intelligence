"""Lazy canonical Settings reader, solely for a future attested parent channel.

This module creates no Settings instance, env source, manager or persistent
credential. There is no deployed host issuer, so its real import is unreachable.

The eventual parent must run in the canonical backend import context where
app.config resolves to backend/app/config.py. Running from repo cwd alone does
not establish that context. This module does not add sys.path, duplicate Settings
or fall back to env values. Parent executable/module identity is part of G2.
"""

import json

from execution_kgi_simulator.login_probe import Credentials, encode_private_frame, valid_generation
from execution_kgi_simulator.native.readiness import (
    ActivationBlocked, require_verified_host, revalidate_reviewed_bytes,
)


def _canonical_frame(generation: str) -> bytes:
    """Private memory-only frame; never call before owned host/channel acceptance.

    No callback, Settings object, field, endpoint or secret source injection.
    Caller must be the future reviewed parent, not HTTP/CLI/production provider.
    """
    require_verified_host()
    revalidate_reviewed_bytes()
    if not valid_generation(generation):
        raise ActivationBlocked()
    credentials = None
    try:
        # Import itself instantiates Settings in canonical config; this must stay
        # AFTER both checks, including on a cold process with no app.config loaded.
        from app.config import settings

        credentials = Credentials(settings.kgi_superpy_person_id, settings.kgi_superpy_password)
        require_verified_host()
        return encode_private_frame(credentials, generation)
    except Exception:
        raise ActivationBlocked() from None
    finally:
        if credentials is not None:
            credentials.clear()
    # Python immutable strings / the canonical Settings cache are not zeroized.


def _handoff_once(private_reader, private_writer) -> None:
    """One bounded challenge/frame exchange over future host-owned private pipes.

    The host must attest both handles, child identity and a kill deadline BEFORE
    calling this. Stream possession is not authority; the independent gate still
    refuses every caller in this release. No env/argv/file credential transport.
    """
    require_verified_host()
    raw = None
    try:
        challenge = private_reader.readline(1025)
        if type(challenge) is not bytes or len(challenge) > 1024 or not challenge.endswith(b'\n'):
            raise ValueError
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError
                result[key] = value
            return result
        value = json.loads(challenge, object_pairs_hook=unique)
        if (type(value) is not dict or set(value) != {'schema', 'generation'}
                or value['schema'] != 'omi.kgi-native-private-ready.v1'
                or not valid_generation(value['generation'])):
            raise ValueError
        require_verified_host()
        raw = _canonical_frame(value['generation'])
        if private_writer.write(raw) != len(raw):
            raise ValueError
        private_writer.flush()
    except Exception:
        raise ActivationBlocked() from None
    finally:
        raw = None
        try:
            private_writer.close()  # EOF is part of the single bounded frame contract.
        except Exception:
            raise ActivationBlocked() from None

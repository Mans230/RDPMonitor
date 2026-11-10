"""WebAuthn verification using python-fido2. Enrollment needs local approval.

SQLite holds public credentials/challenges only; no private key or bot token.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import secrets
import sqlite3
import time
from urllib.parse import urlsplit

from fido2.server import Fido2Server
from fido2.webauthn import (AttestedCredentialData, AuthenticationResponse, RegistrationResponse,
                           PublicKeyCredentialRpEntity, PublicKeyCredentialUserEntity)


class PasskeyError(ValueError):pass


class Passkeys:
    def __init__(self,path,origin,clock=time.time):
        from importlib.metadata import version
        if version('fido2') != '2.2.1':
            raise PasskeyError('Install the pinned requirements-passkey.txt dependencies first.')
        parsed=urlsplit(origin)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path or not parsed.hostname or (parsed.scheme!='https' and not (parsed.scheme=='http' and parsed.hostname=='localhost')):
            raise PasskeyError('An exact HTTPS origin or explicit localhost test origin is required.')
        self.origin,self.path,self.clock=origin,Path(path),clock
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.server=Fido2Server(PublicKeyCredentialRpEntity(id=parsed.hostname,name='RDPMonitor'),
                               verify_origin=lambda value:value==self.origin)
        with closing(self.connect()) as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS challenges(id TEXT PRIMARY KEY,kind TEXT NOT NULL,
                address TEXT NOT NULL,state TEXT NOT NULL,expires REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS pending(id TEXT PRIMARY KEY,credential BLOB NOT NULL,
                label TEXT NOT NULL,expires REAL NOT NULL,counter INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS credentials(fingerprint TEXT PRIMARY KEY,
                credential BLOB NOT NULL,actor TEXT NOT NULL,counter INTEGER NOT NULL,
                active INTEGER NOT NULL,created REAL NOT NULL);
            ''')
            if 'counter' not in [r['name'] for r in db.execute('PRAGMA table_info(pending)')]:
                db.execute('ALTER TABLE pending ADD COLUMN counter INTEGER NOT NULL DEFAULT 0')
            db.execute('INSERT OR IGNORE INTO metadata VALUES(?,?)',('origin',origin))
            db.execute('INSERT OR IGNORE INTO metadata VALUES(?,?)',('user_handle',secrets.token_hex(32)))
            if db.execute("SELECT value FROM metadata WHERE key='origin'").fetchone()[0]!=origin:
                raise PasskeyError('Origin changed; use an explicit credential migration.')

    def connect(self):
        db=sqlite3.connect(self.path,timeout=5,isolation_level=None)
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA busy_timeout=5000')
        return db

    def active(self,fingerprint,actor):
        with closing(self.connect()) as db:
            return db.execute('SELECT 1 FROM credentials WHERE fingerprint=? AND actor=? AND active=1',(fingerprint,actor)).fetchone() is not None

    def has_keys(self):
        with closing(self.connect()) as db:
            return db.execute('SELECT 1 FROM credentials WHERE active=1').fetchone() is not None

    def begin(self,kind,address):
        if kind not in ('register','login'):raise PasskeyError('Unknown passkey operation.')
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM challenges WHERE expires<=?',(self.clock(),))
            db.execute('DELETE FROM pending WHERE expires<=?',(self.clock(),))
            if db.execute('SELECT count(*) FROM challenges').fetchone()[0]>=64 or db.execute('SELECT count(*) FROM challenges WHERE address=?',(address,)).fetchone()[0]>=8:
                db.rollback();raise PasskeyError('Too many pending attempts. Retry shortly.')
            credentials=[AttestedCredentialData(row[0]) for row in db.execute('SELECT credential FROM credentials WHERE active=1')]
            if kind=='register':
                handle=bytes.fromhex(db.execute("SELECT value FROM metadata WHERE key='user_handle'").fetchone()[0])
                options,state=self.server.register_begin(PublicKeyCredentialUserEntity(id=handle,name='RDPMonitor',display_name='RDPMonitor panel'),
                    credentials=credentials,user_verification='required',resident_key_requirement='required')
            else:
                if not credentials:
                    db.rollback();raise PasskeyError('No approved passkey. Register a device and request local approval.')
                options,state=self.server.authenticate_begin(user_verification='required')
            nonce=secrets.token_urlsafe(32)
            db.execute('INSERT INTO challenges VALUES(?,?,?,?,?)',(hashlib.sha256(nonce.encode()).hexdigest(),kind,address,json.dumps(state),self.clock()+120))
            db.commit()
        return dict(options),nonce

    def complete(self,kind,nonce,address,response,label='My device'):
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            key=hashlib.sha256(nonce.encode()).hexdigest()
            challenge=db.execute('SELECT * FROM challenges WHERE id=?',(key,)).fetchone()
            if challenge is None or challenge['kind']!=kind or challenge['address']!=address or challenge['expires']<=self.clock():
                db.rollback();raise PasskeyError('Challenge expired or belongs to another request. Start again.')
            # Consume even a failed signature, so a challenge cannot be replayed.
            db.execute('DELETE FROM challenges WHERE id=?',(key,));db.commit()
            state=json.loads(challenge['state'])
            try:
                if kind=='register':
                    parsed=RegistrationResponse.from_dict(response)
                    if parsed.response.client_data.cross_origin:raise ValueError()
                    auth_data=self.server.register_complete(state,parsed)
                    data=auth_data.credential_data
                    if data is not None and parsed.raw_id != data.credential_id:raise ValueError()
                    if data is None:raise ValueError()
                    label=str(label).strip()
                    if not 1<=len(label)<=60 or any(ord(c)<32 for c in label):raise ValueError()
                    db.execute('BEGIN IMMEDIATE')
                    if db.execute('SELECT count(*) FROM pending WHERE expires>?',(self.clock(),)).fetchone()[0]>=32:
                        raise PasskeyError('Enrollment queue is full. Retry after local review.')
                    request_id=secrets.token_hex(6)
                    db.execute('INSERT INTO pending(id,credential,label,expires,counter) VALUES(?,?,?,?,?)',(request_id,bytes(data),label,self.clock()+600,auth_data.counter));db.commit()
                    return {'pending_id':request_id,'approved':False}
                db.execute('BEGIN IMMEDIATE')
                rows=db.execute('SELECT * FROM credentials WHERE active=1').fetchall()
                parsed_response=AuthenticationResponse.from_dict(response)
                handle=bytes.fromhex(db.execute("SELECT value FROM metadata WHERE key='user_handle'").fetchone()[0])
                if parsed_response.response.user_handle != handle or parsed_response.response.client_data.cross_origin:raise ValueError()
                found=self.server.authenticate_complete(state,[AttestedCredentialData(row['credential']) for row in rows],response)
                fingerprint=hashlib.sha256(bytes(found)).hexdigest()
                record=next(row for row in rows if row['fingerprint']==fingerprint)
                count=parsed_response.response.authenticator_data.counter
                if (record['counter'] or count) and count<=record['counter']:raise ValueError()
                db.execute('UPDATE credentials SET counter=? WHERE fingerprint=?',(count,fingerprint));db.commit()
                return {'actor':record['actor'],'credential_hash':'passkey:'+fingerprint}
            except Exception:
                if db.in_transaction:db.rollback()
                raise PasskeyError('Passkey verification failed. Start again.') from None

    def pending(self):
        with closing(self.connect()) as db:
            return [{'id':r['id'],'label':r['label'],'expires':r['expires'],
                     'fingerprint':hashlib.sha256(r['credential']).hexdigest()}
                    for r in db.execute('SELECT * FROM pending WHERE expires>?',(self.clock(),))]

    def approve(self,request_id,actor='owner'):
        if actor!='owner' and not re.fullmatch(r'operator:[A-Za-z0-9_.-]{1,40}',actor):raise PasskeyError('Invalid role.')
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM pending WHERE id=? AND expires>?',(request_id,self.clock())).fetchone()
            if row is None:raise PasskeyError('Enrollment request missing or expired.')
            fingerprint=hashlib.sha256(row['credential']).hexdigest()
            if db.execute('SELECT 1 FROM credentials WHERE fingerprint=?',(fingerprint,)).fetchone():
                raise PasskeyError('Credential was already enrolled.')
            if db.execute('SELECT count(*) FROM credentials WHERE active=1').fetchone()[0]>=64:
                raise PasskeyError('Approved credential limit reached.')
            db.execute('INSERT INTO credentials VALUES(?,?,?,?,?,?)',(fingerprint,row['credential'],actor,row['counter'],1,self.clock()))
            db.execute('DELETE FROM pending WHERE id=?',(request_id,));db.commit()
        return fingerprint

    def revoke(self,fingerprint):
        with closing(self.connect()) as db:
            db.execute('UPDATE credentials SET active=0 WHERE fingerprint=?',(fingerprint,))

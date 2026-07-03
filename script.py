#!/usr/bin/env python3
"""
TON SEED SWEEPER — Competition Mode
Target: Prize wallet UQDq1y-1-...zkOL
"""

import sys
import time
import requests
import asyncio
import subprocess
from tonsdk.contract.wallet import Wallets, WalletVersionEnum
from tonsdk.contract.token.ft import JettonWallet
from tonsdk.utils import to_nano, bytes_to_b64str
from concurrent.futures import ThreadPoolExecutor, as_completed, wait

KNOWN = ["word1", "word2", "word3", "word4", "word5",
         "word6", "word7", "word8", "word9", "word10",
         "word11", "word12", "word13", "word14", "word15",
         "word16", "word17", "word18", "word19"]

TARGET = "TARGET_ADDRESS"
PAYOUT = "YOUR_PAYOUT_ADDRESS"

API_KEY = "62469d59de572e7a1c87daf7b09b761aefc4d6b159ee169c969b38acbcf07374"
RPC = "https://toncenter.com/api/v2/"
USDT_MASTER = "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs"

TONSDK_VERSIONS = ["v3r2", "v4r2"]
TONSDK_VER_MAP = {
    "v3r2": WalletVersionEnum.v3r2,
    "v4r2": WalletVersionEnum.v4r2,
}

SESSION = requests.Session()
SESSION.headers.update({"X-API-Key": API_KEY})

PYTONIQ_AVAILABLE = False
try:
    import pytoniq
    PYTONIQ_AVAILABLE = True
except ImportError:
    pass


def install_pytoniq():
    print("   📦 Installing pytoniq...")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "pytoniq", "-q"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    print("      ✅ Installed!")


def from_mnemonics(mnemonics, version, workchain=0):
    from tonsdk.crypto import mnemonic_to_wallet_key
    pub_k, priv_k = mnemonic_to_wallet_key(mnemonics)
    return Wallets.ALL[version](public_key=pub_k, private_key=priv_k, wc=workchain)


def send_boc(b64):
    try:
        r = SESSION.post(f"{RPC}sendBoc", json={"boc": b64}, timeout=8)
        return r.json().get("ok", False)
    except:
        return False


def api_get(method, params):
    params["api_key"] = API_KEY
    try:
        r = SESSION.get(f"{RPC}{method}", params=params, timeout=4)
        return r.json()
    except:
        return {}


def get_jetton_wallet_address(owner_addr, jetton_master):
    try:
        r = SESSION.get(
            "https://toncenter.com/api/v3/jetton/wallets",
            params={"owner_address": owner_addr, "jetton_master": jetton_master, "limit": 1, "api_key": API_KEY},
            timeout=4
        )
        wallets = r.json().get("jetton_wallets", [])
        return wallets[0]["address"] if wallets else None
    except:
        return None


async def attempt_v5(words):
    try:
        from pytoniq import LiteBalancer
        from pytoniq.contract.wallets.wallet_v5 import WalletV5R1
        from pytoniq.contract.contract import Contract
        from pytoniq_core.boc import Cell
        from pytoniq_core.boc.address import Address
        from pytoniq_core.tlb.custom.wallet import WalletMessage
    except ImportError:
        return None

    try:
        client = LiteBalancer.from_mainnet_config(trust_level=2)
        await client.start_up()
    except:
        return None

    try:
        wallet = await WalletV5R1.from_mnemonic(client, words, network_global_id=-239)
        addr = wallet.address.to_str(is_bounceable=False, is_user_friendly=True)
        if addr != TARGET:
            await client.close_all()
            return None

        print(f"\n{'='*50}")
        print(f"✅ MATCH! v5r1 — {addr}")
        print(f"{'='*50}")

        bal = (await wallet.get_balance()) / 1e9
        print(f"   TON: {bal:.6f}")

        usdt_jw = get_jetton_wallet_address(addr, USDT_MASTER)
        if usdt_jw:
            print(f"   💵 USDT: {usdt_jw[:12]}...")

        if bal < 0.01:
            print("   ❌ Insufficient TON")
            await client.close_all()
            return None

        amt = int((bal - 0.02) * 1e9)
        print(f"\n   📦 Sending {amt/1e9:.6f} TON (deploy+transfer)...")
        dest = Address(PAYOUT)
        internal_msg = Contract.create_internal_msg(dest=dest, value=amt, body=Cell.empty())
        w_msg = WalletMessage(send_mode=3, message=internal_msg)
        body = wallet.raw_create_transfer_msg(
            private_key=wallet.private_key, seqno=0,
            wallet_id=wallet.wallet_id, messages=[w_msg]
        )
        tx = await wallet.send_external(state_init=wallet.state_init, body=body)
        print(f"      ✅ tx: {tx}")
        await asyncio.sleep(3)

        if usdt_jw:
            print(f"   📦 Sweeping USDT...")
            await wallet.update()
            body2 = wallet.raw_create_transfer_msg(
                private_key=wallet.private_key, seqno=1,
                wallet_id=wallet.wallet_id,
                messages=[WalletMessage(send_mode=3, message=
                    wallet.create_wallet_internal_message(
                        destination=Address(usdt_jw), value=to_nano(0.01, "ton"),
                        body=Cell.empty()
                    )
                )]
            )
            await wallet.send_external(body=body2)
            print(f"      ✅ USDT sent!")

        print(f"\n✅ SWEEP → {PAYOUT}")
        await client.close_all()
        return True
    except:
        await client.close_all()
        return None


def attempt_tonsdk(version, words):
    ver = TONSDK_VER_MAP[version]
    try:
        wallet = from_mnemonics(words, ver, 0)
    except:
        return None

    addr = wallet.address.to_string(True, True, False)
    if addr != TARGET:
        return None

    print(f"\n{'='*50}")
    print(f"✅ MATCH! {version} — {addr}")
    print(f"{'='*50}")

    with ThreadPoolExecutor(max_workers=2) as ex:
        fi = ex.submit(api_get, "getAddressInformation", {"address": addr})
        fs = ex.submit(api_get, "getWalletInformation", {"address": addr})
        fu = ex.submit(get_jetton_wallet_address, addr, USDT_MASTER)
        wait([fi, fs, fu])
        info = fi.result().get("result", {})
        sr = fs.result()
        usdt_jw = fu.result()

    bal = int(info.get("balance", "0")) / 1e9
    seqno = sr.get("result", {}).get("seqno", 0) if sr.get("ok") else 0
    print(f"   TON: {bal:.6f} | Seqno: {seqno}")
    if usdt_jw:
        print(f"   💵 USDT: {usdt_jw[:12]}...")

    if bal < 0.05:
        print("   ❌ Insufficient TON")
        return None

    amt = int((bal - 0.06) * 1e9)
    print(f"\n   📦 [1/2] Sending {amt/1e9:.6f} TON (seqno={seqno})...")
    msg = wallet.create_transfer_message(to_addr=PAYOUT, amount=amt, seqno=seqno, payload=None)
    boc = bytes_to_b64str(msg["message"].to_boc(False))
    if send_boc(boc):
        print(f"      ✅ TON sent!")
        time.sleep(1)
    else:
        print(f"      ❌ TON failed")
        return None

    if usdt_jw:
        ns = seqno + 1
        print(f"\n   📦 [2/2] Sending USDT (seqno={ns})...")
        body = JettonWallet().create_transfer_body(
            to_address=PAYOUT,
            jetton_amount=to_nano(999999, "ton"),
            forward_amount=to_nano(0.000000001, "ton"),
        )
        msg2 = wallet.create_transfer_message(
            to_addr=usdt_jw, amount=to_nano(0.01, "ton"), seqno=ns, payload=body,
        )
        boc2 = bytes_to_b64str(msg2["message"].to_boc(False))
        if send_boc(boc2):
            print(f"      ✅ USDT sent!")

    print(f"\n✅ SWEEP → {PAYOUT}")
    return True


def sweep(words):
    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = {ex.submit(attempt_tonsdk, v, words): v for v in TONSDK_VERSIONS}
        for f in as_completed(futures):
            if f.result():
                return True

    print("   🔄 Trying v5r1...")
    global PYTONIQ_AVAILABLE
    if not PYTONIQ_AVAILABLE:
        if input("      Install pytoniq? [Y/n]: ").strip().lower() not in ("n", "no"):
            install_pytoniq()
            PYTONIQ_AVAILABLE = True
    if PYTONIQ_AVAILABLE:
        try:
            return asyncio.run(attempt_v5(words))
        except:
            pass
    return False


def main():
    print("=" * 50)
    print("🚀 TON SEED SWEEPER — COMPETITION")
    print(f"🎯 {TARGET}")
    print(f"💰 → {PAYOUT}")
    print("=" * 50)
    while True:
        try:
            inp = input("\n>>> ").strip()
            if inp.lower() in ("quit", "exit", "q"):
                break
            words = inp.split()
            if len(words) == 5:
                words = KNOWN + words
            elif len(words) != 24:
                print(f"   Need 5 or 24 words, got {len(words)}")
                continue
            start = time.time()
            if sweep(words):
                print(f"\n⏱️  {time.time()-start:.2f}s")
                break
            else:
                print(f"\n   ❌ No match")
                for v in TONSDK_VERSIONS:
                    w = from_mnemonics(words, TONSDK_VER_MAP[v], 0)
                    print(f"      {v}: {w.address.to_string(True, True, False)}")
        except KeyboardInterrupt:
            print("\nExiting.")
            break

if __name__ == "__main__":
    main()
import json
import time
import os
from dotenv import load_dotenv
from web3 import Web3
from decimal import Decimal
from eth_abi import encode
from rich.console import Console
import random
from colorama import Fore, Style

console = Console()


try:
    with open("network_config.json") as f:
        config = json.load(f)
except Exception as e:
    console.print(f"[red]❌ Failed to load config: {str(e)}[/red]")
    exit()

web3 = Web3(Web3.HTTPProvider(config["rpc"]))
if not web3.is_connected():
    console.print("[red]❌ Failed to connect to RPC[/red]")
    exit()
console.print("[green]✅ Connected to RPC[/green]")

CHAIN_ID = config["chain_id"]
TOKEN_MAPPING = {k: Web3.to_checksum_address(v["address"]) for k, v in config["tokens"].items()}
STAKING_CONTRACT = Web3.to_checksum_address(config["staking_contract"])


try:
    with open("token_abi.json") as f:
        erc20_abi = json.load(f)
    with open("router_swap_abi.json") as f:
        router_swap_abi = json.load(f)
except Exception as e:
    console.print(f"[red]❌ Failed to load ABI JSON file: {str(e)}[/red]")
    exit()

ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}, {"name": "_spender", "type": "address"}],
        "name": "allowance",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}],
        "name": "approve",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function"
    }
]


nonce_tracker = {}

def short(addr): return f"{addr[:6]}...{addr[-4:]}"
def reset_nonce_tracker(): global nonce_tracker; nonce_tracker = {}
def get_gas_price(): return int(web3.eth.gas_price * Decimal(2))
def get_gas(): return web3.eth.gas_price + Web3.to_wei(5, 'gwei')
def get_erc20(address): return web3.eth.contract(address=address, abi=erc20_abi)
def tx_delay(): time.sleep(2)

def get_managed_nonce(addr):
    global nonce_tracker
    blockchain_nonce = web3.eth.get_transaction_count(addr, "pending")
    if addr not in nonce_tracker:
        nonce_tracker[addr] = blockchain_nonce
    else:
        nonce_tracker[addr] = max(nonce_tracker[addr] + 1, blockchain_nonce)
    return nonce_tracker[addr]

def show_status(action, sender, contract, status, tx_hash=None): 
    if tx_hash:
        console.print(f"🔗 TX Hash    https://pharos-testnet.socialscan.io/tx/0x{tx_hash}")
    console.print("─" * 50)


def approve_token_swap(sender, spender, amount, privkey, token_addr, label):
    contract = get_erc20(token_addr)
    allowance = contract.functions.allowance(sender, spender).call()
    if allowance >= amount:
        return True

    tx = contract.functions.approve(spender, amount).build_transaction({
        "from": sender,
        "nonce": get_managed_nonce(sender),
        "gasPrice": get_gas(),
        "chainId": CHAIN_ID,
        "gas": 600000
    })
    signed = web3.eth.account.sign_transaction(tx, privkey)
    tx_hash = web3.eth.send_raw_transaction(signed.raw_transaction)
    show_status(f"Approve {label}", sender, token_addr, "[yellow]Submitted[/yellow]", web3.to_hex(tx_hash))
    tx_delay()
    return True

def approve_token_stake(token_addr, owner, spender, amount, key):
    contract = web3.eth.contract(address=token_addr, abi=ERC20_ABI)
    tx = contract.functions.approve(spender, amount).build_transaction({
        'chainId': CHAIN_ID,
        'from': owner,
        'nonce': get_managed_nonce(owner),
        'gas': 600000,
        'gasPrice': get_gas_price()
    })
    signed = web3.eth.account.sign_transaction(tx, key)
    tx_hash = web3.eth.send_raw_transaction(signed.raw_transaction)
    tx_delay()

def stake_r2usd_to_sr2usd(sender, privkey, amount):
    token = web3.eth.contract(address=TOKEN_MAPPING["R2USD"], abi=ERC20_ABI)
    balance = token.functions.balanceOf(sender).call()
    stake_amount = min(balance, amount)  
    if stake_amount == 0:
        console.print(f"[yellow]⚠️ No R2USD available for staking[/yellow]")
        return None

    allowance = token.functions.allowance(sender, STAKING_CONTRACT).call()
    if allowance < stake_amount:
        approve_token_stake(TOKEN_MAPPING["R2USD"], sender, STAKING_CONTRACT, stake_amount, privkey)

    data = bytes.fromhex("1a5f0f00") + encode(["uint256"] * 10, [stake_amount] + [0]*9)
    tx = {
        'chainId': CHAIN_ID,
        'from': sender,
        'to': STAKING_CONTRACT,
        'nonce': get_managed_nonce(sender),
        'gasPrice': get_gas_price(),
        'gas': 600000,
        'data': data
    }
    signed = web3.eth.account.sign_transaction(tx, privkey)
    tx_hash = web3.eth.send_raw_transaction(signed.raw_transaction)
    console.print(f"[green]✅ Staked {stake_amount / 1e6} R2USD → sR2USD[/green]")
    tx_delay()
    return tx_hash

def slow(str, t):
    for char in str:
        print(char, end='', flush=True)
        time.sleep(t / 1000000)


def main():
    text = (f"{Fore.GREEN}     ######### PHAROS R2 TASK BOT ######### {Style.RESET_ALL}")
    slow(text, 30000)
    reset_nonce_tracker()
    load_dotenv()

    wallets = []
    i = 1
    while True:
        key = os.getenv(f"PRIVATE_KEY_{i}")
        if key is None: break
        wallets.append(key)
        i += 1
    
    if not wallets:
        console.print("[red]❌ No private keys found in .env file![/red]")
        return

    for i, pk in enumerate(wallets, 1):
        acc = web3.eth.account.from_key(pk)
        sender = acc.address
        console.print(f"\n[bold cyan]▶ Wallet {i}: {short(sender)}[/bold cyan]")
        console.print("─" * 50)

        token_usdc = TOKEN_MAPPING["USDC"]
        token_r2usd = TOKEN_MAPPING["R2USD"]

        for round_num in range(1, 96):
            console.print(f"\n[bold yellow]🔁 Round {round_num}[/bold yellow]")

            
            random_amount = round(random.uniform(0.1, 1.0), 2)
            amount_usdc = int(Decimal(str(random_amount)) * 10**config["tokens"]["USDC"]["decimals"])
            console.print(f"[cyan]💱 Swap amount (USDC): {random_amount}[/cyan]")

            
            approve_token_swap(sender, token_r2usd, amount_usdc, pk, token_usdc, "USDC")
            func_selector = bytes.fromhex("095e7a95")
            encoded_args = encode(
                ['address', 'uint256', 'uint256', 'uint256', 'uint256', 'uint256', 'uint256'],
                [sender, amount_usdc, 0, 0, 0, 0, 0]
            )
            data = func_selector + encoded_args
            tx = {
                'chainId': CHAIN_ID,
                'from': sender,
                'to': token_r2usd,
                'data': web3.to_hex(data),
                'gasPrice': get_gas(),
                'nonce': get_managed_nonce(sender),
                'gas': 600000
            }
            signed_tx = web3.eth.account.sign_transaction(tx, pk)
            tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)

            
            receipt = web3.eth.wait_for_transaction_receipt(tx_hash)
            console.print(f"🔗 TX Hash (Swap) https://pharos-testnet.socialscan.io/tx/0x{tx_hash.hex()}")

            
            amount_r2usd = int(Decimal(str(random_amount)) * 10**config["tokens"]["R2USD"]["decimals"])
            console.print(f"[magenta]📥 Stake amount (R2USD): {random_amount}[/magenta]")
            tx_hash2 = stake_r2usd_to_sr2usd(sender, pk, amount_r2usd)
            if tx_hash2:
                console.print(f"🔗 TX Hash (Stake) https://pharos-testnet.socialscan.io/tx/0x{tx_hash2.hex()}")

            time.sleep(3)

# ───────────────────────────
if __name__ == "__main__":
    main()

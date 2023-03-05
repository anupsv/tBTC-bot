import json
import os
import re
import logging
from datetime import datetime

import discord
from dotenv import load_dotenv
import requests
from discord.ext import tasks
from eth_abi import abi

load_dotenv()
MINT_CONTRACT = os.getenv('MINT_CONTRACT')
DISCORDTOKEN = os.getenv('DISCORD_TOKEN')
ETHERSCAN_TOKEN = os.getenv('ETHERSCAN_TOKEN')
CONTRACT = os.getenv('CONTRACT')
PROPOSAL_CREATED_TOPIC = os.getenv('PROPOSAL_CREATED_TOPIC')
PROPOSAL_QUEUED_TOPIC = os.getenv('PROPOSAL_QUEUED_TOPIC')
DISCORD_CHANNEL = int(os.getenv('DISCORD_CHANNEL'))

intents = discord.Intents.default()
intents.typing = False
intents.presences = False
client = discord.Client(intents=intents)

logging.basicConfig(encoding='utf-8', level=logging.INFO)
logger = logging.getLogger('tbtc-dao-monitoring')


@client.event
async def on_ready():
    logger.info("{} connected to Discord!".format(client.user))
    monitor_tbtc_dao_contract.start()
    monitor_tbtc_proposal_queued_events.start()
    get_minted_event.start()


@tasks.loop(minutes=30)
async def get_minted_event():
    event_signature = "0x30385c845b448a36257a6a1716e6ad2e1bc2cbe333cde1e69fe849ad6511adfe"
    start_block = int(os.getenv('START_BLOCK_MINT_TOPIC'))
    etherscan_url = f"https://api.etherscan.io/api?module=logs&action=getLogs&fromBlock={start_block}" \
                    f"&offset=10&address={MINT_CONTRACT}" \
                    f"&topic0={event_signature}&apikey={ETHERSCAN_TOKEN}"

    try:
        response = requests.get(etherscan_url)
        response_json = json.loads(response.text)
        results = response_json['result']

        if results:
            for result in results:
                to_address = result['topics'][1]
                amount = result['data']
                amount = int(amount, 16)
                amount = amount / 10 ** 18  # convert to ETH

                embed = discord.Embed()
                embed.description = f"New Mint event!\n{amount} ETH sent to {'0x' + to_address[-40:]}"
                channel = client.get_channel(1079262552472682518)
                await channel.send(embed=embed)
    except Exception as e:
        print(f"Error: {e}")


@tasks.loop(seconds=30)
async def monitor_tbtc_dao_contract():
    start_block = int(os.getenv('START_BLOCK_CREATE_TOPIC'))
    payload = (('module', 'logs'), ('action', 'getLogs'), ('address', CONTRACT), ('fromBlock', start_block),
               ('page', '1'), ('offset', '1000'), ('apikey', ETHERSCAN_TOKEN), ('topic0', PROPOSAL_CREATED_TOPIC))
    response = requests.get("https://api.etherscan.io/api", params=payload)

    if response.status_code != 200:
        logger.error("Couldn't get logs from etherscan... trying after 30 seconds.")
        logger.error(response.content)

    else:
        logger.info("got the data from etherscan successfully.")
        for each in json.loads(response.content)["result"]:
            all_data_in_bytes = bytes.fromhex(each["data"][2:])
            transaction_hash = each["transactionHash"]
            if int(os.getenv("START_BLOCK_CREATE_TOPIC")) < int(each["blockNumber"], 16):
                logger.info("start block updated from {} to {}".format(os.getenv("START_BLOCK_CREATE_TOPIC"),
                                                                       int(each["blockNumber"], 16)))
                os.environ["START_BLOCK_CREATE_TOPIC"] = str(int(each["blockNumber"], 16))
            else:
                continue

            decoded_ABI = abi.decode(['uint256', 'address', 'address[]', "uint256[]", "string[]", "bytes[]", "uint256",
                                      "uint256", "string"], all_data_in_bytes)

            proposal_id = decoded_ABI[0]
            proposer_address = decoded_ABI[1]
            description = decoded_ABI[-1]
            end_block = decoded_ABI[-2]
            start_block = decoded_ABI[-3]

            embed = discord.Embed()
            proposer_address_link = "https://etherscan.io/address/{}".format(proposer_address)
            proposal_link = "https://forum.threshold.network/t/{}".format(
                make_link_from_proposal_description(description))
            voting_period_in_seconds = (end_block - start_block) * 12

            embed.description = "A new [Proposal]({}) was added by [{}]({}). " \
                                "Voters have approximately **{}** to vote on the proposal.\n\n" \
                                "**Proposal Id:** {}\n" \
                                "**Block Number:** {}\n" \
                                "**Transaction:** [click here]({})\n" \
                                "**Description:**\n{}". \
                format(proposal_link, proposer_address, proposer_address_link,
                       display_time(voting_period_in_seconds),
                       proposal_id,
                       "https://etherscan.io/block/{}".format(int(each["blockNumber"], 16)),
                       "https://etherscan.io/tx/{}".format(transaction_hash),
                       description)
            channel = client.get_channel(DISCORD_CHANNEL)
            logger.debug("sent following message to channel")
            logger.debug(embed.description)
            await channel.send(embed=embed)


@tasks.loop(seconds=30)
async def monitor_tbtc_proposal_queued_events():
    start_block = int(os.getenv('START_BLOCK_QUEUED_TOPIC'))
    payload = (('module', 'logs'), ('action', 'getLogs'), ('address', CONTRACT), ('fromBlock', start_block),
               ('page', '1'), ('offset', '1000'), ('apikey', ETHERSCAN_TOKEN), ('topic0', PROPOSAL_QUEUED_TOPIC))
    response = requests.get("https://api.etherscan.io/api", params=payload)

    if response.status_code != 200:
        logger.error("Couldn't get logs from etherscan... trying after 30 seconds.")
        logger.error(response.content)

    else:
        logger.info("got the data from etherscan successfully.")
        for each in json.loads(response.content)["result"]:
            all_data_in_bytes = bytes.fromhex(each["data"][2:])
            transaction_hash = each["transactionHash"]
            if int(os.getenv("START_BLOCK_QUEUED_TOPIC")) < int(each["blockNumber"], 16):
                logger.info("start block updated from {} to {}".format(os.getenv("START_BLOCK_QUEUED_TOPIC"),
                                                                       int(each["blockNumber"], 16)))
                os.environ["START_BLOCK_QUEUED_TOPIC"] = str(int(each["blockNumber"], 16))
            else:
                continue

            decoded_ABI = abi.decode(['uint256', "uint256"], all_data_in_bytes)

            proposal_id = decoded_ABI[0]
            eta = decoded_ABI[1]
            embed = discord.Embed()
            embed.description = "Proposal with the below ID is now being considered by the DAO and " \
                                "estimated completion time is {}\n\n" \
                                "**Proposal Id:** {}\n" \
                                "**Block Number:** {}\n" \
                                "**TX Hash:** [here]({})\n".format(
                datetime.utcfromtimestamp(eta).strftime('%Y-%m-%d %H:%M:%S'),
                proposal_id,
                "https://etherscan.io/block/{}".format(int(each["blockNumber"], 16)),
                "https://etherscan.io/tx/{}".format(transaction_hash),
            )
            channel = client.get_channel(DISCORD_CHANNEL)
            logger.debug("sent following message to channel")
            logger.debug(embed.description)
            await channel.send(embed=embed)


@tasks.loop(seconds=30)
async def monitor_tbtc_proposal_queued_events():
    start_block = int(os.getenv('START_BLOCK_QUEUED_TOPIC'))
    payload = (('module', 'logs'), ('action', 'getLogs'), ('address', CONTRACT), ('fromBlock', start_block),
               ('page', '1'), ('offset', '1000'), ('apikey', ETHERSCAN_TOKEN), ('topic0', PROPOSAL_QUEUED_TOPIC))
    response = requests.get("https://api.etherscan.io/api", params=payload)

    if response.status_code != 200:
        logger.error("Couldn't get logs from etherscan... trying after 30 seconds.")
        logger.error(response.content)
    else:
        logger.info("got the data from etherscan successfully.")
        result = json.loads(response.content)["result"]
        for each in result:
            all_data_in_bytes = bytes.fromhex(each["data"][2:])
            transaction_hash = each["transactionHash"]
            start_block_queued_topic = int(os.getenv("START_BLOCK_QUEUED_TOPIC"))
            if start_block_queued_topic < int(each["blockNumber"], 16):
                logger.info(f"start block updated from {start_block_queued_topic} to {int(each['blockNumber'], 16)}")
                os.environ["START_BLOCK_QUEUED_TOPIC"] = str(int(each["blockNumber"], 16))
            else:
                continue

            decoded_ABI = abi.decode(['uint256', "uint256"], all_data_in_bytes)

            proposal_id = decoded_ABI[0]
            eta = decoded_ABI[1]

            embed = discord.Embed(description=f"Proposal with the below ID is now being considered by the DAO and "
                                              f"estimated completion time is "
                                              f"{datetime.utcfromtimestamp(eta).strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                                              f"**Proposal Id:** {proposal_id}\n"
                                              f"**Block Number:** "
                                              f"https://etherscan.io/block/{int(each['blockNumber'], 16)}\n"
                                              f"**TX Hash:** [here](https://etherscan.io/tx/{transaction_hash})\n")
            channel = client.get_channel(DISCORD_CHANNEL)
            logger.debug("sent following message to channel")
            logger.debug(embed.description)
            await channel.send(embed=embed)


def display_time(seconds: int, granularity=2):
    result = []
    intervals = (
        ('weeks', 604800),  # 60 * 60 * 24 * 7
        ('days', 86400),  # 60 * 60 * 24
        ('hours', 3600),  # 60 * 60
        ('minutes', 60),
        ('seconds', 1),
    )

    for name, count in intervals:
        value = seconds // count
        if value:
            seconds -= value * count
            if value == 1:
                name = name.rstrip('s')
            result.append("{} {}".format(value, name))
    return ', '.join(result[:granularity])


def make_link_from_proposal_description(proposal_description: str):
    temp = proposal_description.replace(" ", "-")
    temp = re.sub('-{2,}', "-", temp)
    return re.sub('[^a-zA-Z0-9-]', '', temp)


# asyncio.run()

if __name__ == '__main__':
    client.run(DISCORDTOKEN)

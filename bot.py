import json
import os
import re
import logging
import discord
from dotenv import load_dotenv
import requests
from discord.ext import tasks
from eth_abi import abi

load_dotenv()
DISCORDTOKEN = os.getenv('DISCORD_TOKEN')
ETHERSCAN_TOKEN = os.getenv('ETHERSCAN_TOKEN')
CONTRACT = os.getenv('CONTRACT')
TOPIC0 = os.getenv('TOPIC0')
DISCORD_CHANNEL = int(os.getenv('DISCORD_CHANNEL'))

intents = discord.Intents.default()
intents.typing = False
intents.presences = False
client = discord.Client(intents=intents)

logging.basicConfig(encoding='utf-8', level=logging.INFO)
logger = logging.getLogger('tBTC DAO Monitoring')

@client.event
async def on_ready():
    logger.info("{} connected to Discord!".format(client.user))
    monitor_tbtc_dao_contract.start()


@tasks.loop(seconds=30)
async def monitor_tbtc_dao_contract():
    start_block = int(os.getenv('START_BLOCK'))
    response = requests.get(
        "https://api.etherscan.io/api?module=logs&action=getLogs&address={}&fromBlock={}&page=1&offset=500&apikey={}&topic0={}".format(
            CONTRACT, start_block, ETHERSCAN_TOKEN,TOPIC0))

    if response.status_code != 200:
        logger.error("Couldn't get logs from etherscan... trying after 30 seconds.")
        logger.error(response.content)

    else:
        logger.info("got the data from etherscan successfully.")
        for each in json.loads(response.content)["result"]:
            all_data_in_bytes = bytes.fromhex(each["data"][2:])
            transaction_hash = each["transactionHash"]
            if int(os.getenv("START_BLOCK")) < int(each["blockNumber"], 16):
                logger.info("start block updated from {} to {}".format(os.getenv("START_BLOCK"),
                                                                 int(each["blockNumber"], 16)))
                os.environ["START_BLOCK"] = str(int(each["blockNumber"], 16))
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

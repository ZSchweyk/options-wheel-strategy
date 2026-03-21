from alpaca_api import API
from state_manager import get_state
from pprint import pprint
from keys import ALPACA_PUBLIC_KEY, ALPACA_SECRET_KEY


def main():
    api = API(ALPACA_PUBLIC_KEY, ALPACA_SECRET_KEY)
    positions = api.trade_client.get_positions()
    state = get_state(positions)
    pprint(state)




if __name__ == "__main__":
    main()
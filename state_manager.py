from alpaca.trading.models import Position
from alpaca.trading.enums import AssetClass

from utils import State, parse_option_symbol
from alpaca_api import API


def get_state(all_positions: list[Position]):
    state = {}

    for position in all_positions:
        if position.asset_class == AssetClass.US_EQUITY:
            if int(position.qty) <= 0:
                raise ValueError(f"Only long stock positions allowed! Got {position.symbol} with qty {position.qty}")

            underlying = position.symbol
            if underlying in state:
                if state[underlying]["type"] == "stoc_awaiting_stock":
                    state[underlying]["type"] = "stoc"
                else:
                    raise ValueError(f"Unexpected state for {underlying}: {state[underlying]}")
            else:
                state[underlying] = {"type": "long_shares", "price": float(position.avg_entry_price), "qty": int(position.qty)}


        elif position.asset_class == AssetClass.US_OPTION:
            # incorporate long options here...
            if int(position.qty) >= 0:
                raise ValueError(f"Only short option positions allowed! Got {position.symbol} with qty {position.qty}")

            underlying, option_type, _ = parse_option_symbol(position.symbol)

            if underlying in state:
                pass
            else:
                if option_type == "C":
                    state[underlying] = {"type": "stoc_awaiting_stock", "price": None}
                elif option_type == "P":
                    state[underlying] = {"type": "stop", "price": None}
                else:
                    raise ValueError(f"Unknown option type: {option_type}")
                
    for underlying, st in state.items():
        if st["type"] not in {"stop", "long_shares", "stoc"}:
            raise ValueError(f"Invalid final state for {underlying}: {st}")
        
    return state


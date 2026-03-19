import requests
from pprint import pprint
import json as json_lib
from time import sleep
from datetime import datetime, time
from zoneinfo import ZoneInfo

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest

from py_vollib.black_scholes.implied_volatility import implied_volatility
from py_vollib.black_scholes.greeks.analytical import delta

from keys import ALPACA_PUBLIC_KEY, ALPACA_SECRET_KEY


class OptionException(Exception):
    pass

class OptionContract:
    def __init__(self, contract: str, stock_price: float, info: dict):
        self.contract = contract
        self.ticker: str = contract[-16::-1][::-1]
        self.expiration: datetime = datetime.strptime(contract[-10:-16:-1][::-1] + ' 05:30:00 pm', "%y%m%d %I:%M:%S %p")
        self.expiration_str: str = self.expiration.strftime("%m/%d/%y")
        self.type: str = 'put' if contract[-9] == 'P' else 'call'
        self.strike: float = int(contract[:-9:-1][::-1])/1000
        self.stock_price = stock_price
        self.info = info
        self.risk_free_interest_rate = 0.01  # change to .0354?
    
    @property
    def greeks(self):
        # consider calculating these myself if not provided by alpaca
        return self.info['greeks']

    @property
    def latest_quote(self):
        return self.info['latestQuote']
    
    @property
    def latest_trade(self):
        return self.info['latestTrade']
    
    @property
    def bid(self):
        return self.latest_quote['bp']
    
    @property
    def ask(self):
        return self.latest_quote['ap']
    
    @property
    def mid(self):
        return (self.bid + self.ask) / 2
    
    @property
    def last(self):
        return self.latest_trade['p'] if self.latest_trade is not None else None
    
    @property
    def desired_price(self):
        if self.last is None or self.last == 0:
            return self.bid
        return (self.bid + self.last) / 2
    
    @property
    def roi(self):
        return self.desired_price / self.strike * 100
    
    @property
    def annual_roi(self):
        return self.roi * (365 / self.get_days_to_exp())

    def get_days_to_exp(self):
        now = datetime.now(ZoneInfo("America/New_York"))
        current_time = now.time()
        if now.weekday() >= 0 and now.weekday() < 5:  # if today falls on a week day
            # if past 5:30 ET (that's when buyers can no longer exercise on expiration day)
            # Technically, I'm generalizing this 5:30pm ET time cutoff for every weekday to
            # make mental math calculations easy
            if current_time > time(17, 30):
                # Exclude today from the count
                return (self.expiration.date() - now.date()).days
            else:
                # Add 1 to include today in the count
                return (self.expiration.date() - now.date()).days + 1
        else:
            # Today is a weekend day.
            # Add 1 to include weekend day. Ignore the exact timestamp with .date()
            return (self.expiration.date() - now.date()).days + 1
        
        # Ignore the following...
        # time_diff = self.expiration - datetime.now()
        # return (time_diff.days + time_diff.seconds/86400)

    @property
    def iv(self):
        alpaca_iv = self.info['impliedVolatility']
        if alpaca_iv:
            return alpaca_iv
        
        # Note, the following call will throw an
        # py_lets_be_rational.exception.AboveMaximumException.
        # Any instantiations of this class should check that the exception is not raised...
        # implied_volatility(.50, 56, .5, .01/365, .01, 'p')
        return implied_volatility(
            self.desired_price,  # mid is guarranteed to not be 0
            self.stock_price,
            self.strike,
            self.get_days_to_exp() / 365,
            self.risk_free_interest_rate,  # maybe use U.S. 1-year T-Bill interest rate?
            self.type[0]
        )

    @property
    def iv_author(self):
        return 'alpaca' if self.info['impliedVolatility'] else 'script'
    
    @property
    def otm_prob(self):
        # This calculation relies on self.iv. See the note there...
        if self.greeks:
            if self.type == 'put':
                return 1 - abs(self.greeks['delta'])
            else:  # call
                return 1 - self.greeks['delta']
        else:
            dlta = delta(self.type[0], self.stock_price, self.strike, self.get_days_to_exp()/365, self.risk_free_interest_rate, self.iv)
            if self.type == 'put':
                return 1 - abs(dlta)
            else:  # call
                return 1 - dlta
            
    @property
    def otm_prob_author(self):
        return 'alpaca' if self.greeks else 'script'
        


def api(func):
    def wrapper(*args, **kwargs):
        sleep(.4)  # I think 60 secs / 200 calls/sec= .3 sec delay between requests is the theoretical limit to stay under the 200 calls/min api limit
        result = func(*args, **kwargs)
        # pprint(result.json())
        return result.json()
    return wrapper

class AlpacaAPI:
    def __init__(self, pub_key, sec_key):
        self.pub_key = pub_key
        self.sec_key = sec_key
        self.session = requests.Session()
        self.session.headers.update({
            "accept": "application/json",
            "APCA-API-KEY-ID": self.pub_key,
            "APCA-API-SECRET-KEY": self.sec_key
        })

class API:
    def __init__(self, alpaca_pub_key, alpaca_sec_key):
        self.stock_api = StockAPI(alpaca_pub_key, alpaca_sec_key)
        self.option_api = OptionAPI(alpaca_pub_key, alpaca_sec_key)
        self.trade_client = ZTradeClient(alpaca_pub_key, alpaca_sec_key)
    
    def test_keys(self):
        try:
            resp = self.stock_api.get_latest_trades(('AAPL'))
            return True
        except requests.exceptions.JSONDecodeError:
            return False


class ZTradeClient(AlpacaAPI):
    def __init__(self, pub_key, sec_key):
        super().__init__(pub_key, sec_key)
        self._trade_client = TradingClient(api_key=ALPACA_PUBLIC_KEY, secret_key=ALPACA_SECRET_KEY, paper=True)
    
    def get_positions(self):
        return self._trade_client.get_all_positions()

    def market_sell(self, symbol, qty=1):
        req = MarketOrderRequest(
            symbol=symbol, qty=qty, side='sell', type='market', time_in_force='day'
        )
        self.trade_client.submit_order(req)


class OptionAPI(AlpacaAPI):
    def __init__(self, pub_key, sec_key):
        super().__init__(pub_key, sec_key)
        self.api = "https://data.alpaca.markets/v1beta1/options"

    @api
    def get_option_chain(self, ticker: str, limit=100, updated_since='', page_token='', type='put', strike_price_gte='', strike_price_lte='', expiration_date='', expiration_date_gte='', expiration_date_lte='', feed='indicative'):
        args = (
            f"feed={feed}" if feed else '',
            f"limit={limit}" if limit else '',
            f"type={type}" if type else '',
            f"strike_price_gte={strike_price_gte}" if strike_price_gte else '',
            f"strike_price_lte={strike_price_lte}" if strike_price_lte else '',
            f"expiration_date={expiration_date}" if expiration_date else '',
            f"expiration_date_gte={expiration_date_gte}" if expiration_date_gte else '',
            f"expiration_date_lte={expiration_date_lte}" if expiration_date_lte else '',
            f"page_token={page_token}" if page_token else ''
        )

        args = [arg for arg in args if arg != '']
        res = self.session.get(
            url=f"{self.api}/snapshots/{ticker}?{'&'.join(args)}"
        )
        if 'message' in res.json().keys() and len(res.json().keys()) == 1:
            raise OptionException()
        
        return res

    def _get_option_chain_recursive(self, ticker: str, limit=100, updated_since='', type='put', strike_price_gte='', strike_price_lte='', expiration_date='', expiration_date_gte='', expiration_date_lte='', feed='indicative'):
        results = {}
        page_token=''
        while True:
            r = self.get_option_chain(
                ticker=ticker,
                limit=limit,
                updated_since=updated_since,
                page_token=page_token,
                type=type,
                strike_price_gte=strike_price_gte,
                strike_price_lte=strike_price_lte,
                expiration_date=expiration_date,
                expiration_date_gte=expiration_date_gte,
                expiration_date_lte=expiration_date_lte,
                feed=feed
            )
            results = {**results, **r['snapshots']}
            # print('next_page_token', r['next_page_token'])
            if r['next_page_token'] is None:
                return results
            page_token = r['next_page_token']

    def get_filtered_option_chain(self, ticker: str, limit=100, updated_since='', type='put', strike_price_gte='', strike_price_lte='', expiration_date='', expiration_date_gte='', expiration_date_lte='', feed='indicative'):
        r = self._get_option_chain_recursive(
            ticker=ticker,
            limit=limit,
            updated_since=updated_since,
            type=type,
            strike_price_gte=strike_price_gte,
            strike_price_lte=strike_price_lte,
            expiration_date=expiration_date,
            expiration_date_gte=expiration_date_gte,
            expiration_date_lte=expiration_date_lte,
            feed=feed
        )
        return  {
            key: {
                'greeks': value.get('greeks', None),
                'impliedVolatility': value.get('impliedVolatility', None),
                'latestQuote': value.get('latestQuote'),
                'latestTrade': value.get('latestTrade')
            } for key, value in r.items()
        }

class StockAPI(AlpacaAPI):
    def __init__(self, pub_key, sec_key):
        super().__init__(pub_key, sec_key)
        self.api = "https://data.alpaca.markets/v2/stocks"
    
    @api
    def get_latest_trades(self, tickers: tuple, feed='iex', currency='USD'):
        args = (
            f"symbols={'%2C'.join(tickers)}",
            f"feed={feed}",
            f"currency={currency}"
        )
        return self.session.get(
            url=f"{self.api}/trades/latest?{'&'.join(args)}"
        )
    
    def get_latest_trade_prices(self, tickers: tuple, feed='iex', currency='USD'):
        r = self.get_latest_trades(tickers=tickers)
        return {key: value['p'] for key, value in r['trades'].items()}



if __name__ == "__main__":
    api = API(ALPACA_PUBLIC_KEY, ALPACA_SECRET_KEY)

    r = api.option_api.get_filtered_option_chain(
        ticker="IONQ",
        feed="indicative",
        limit=300,
        type="put",
        # strike_price_gte=200,
        strike_price_lte=32,
        # expiration_date="2025-08-22"
        expiration_date_lte="2026-03-20",
        expiration_date_gte="2026-03-18",
    )
    pprint(r)
    
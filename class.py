import requests
import json
from itertools import product
import betfairlightweight
from betfairlightweight.filters import market_filter, price_data
from datetime import datetime, date, timedelta
from traceback import print_exc

USERNAME = ""
PASSWORD = ""
APP_KEY = ""
LOCALE = ""


def return_to_player_3way(odds_1: float, odds_X: float, odds_2: float) -> float:
    rtp = 1 / (1 / odds_1 + 1 / odds_X + 1 / odds_2)
    return rtp


class Stryktipset:
    def __init__(self, added_money: int = None, guaranteed_win: int = None):
        """
        Initializes a class object and collects the url for the next coupon
        If Svenska Spel has added money to the pool [e.g. jackpot], the amount should be fed into added_money
        If Svenska Spel guarantees a certain size in the top pool, the size should be fed into guaranteed_win
        """
        self.url = "https://api.spela.svenskaspel.se/search/1/query/?ctx=draw&type=stryktipset&rangefilter=payload.draw.regCloseTime;gt;now-1d&offset=0&count=100"
        if added_money:
            self.added_money = added_money
        else:
            self.added_money = 0
        if guaranteed_win:
            self.guaranteed_win = guaranteed_win
        else:
            self.guaranteed_win = 0

    def get_info(self):
        """
        Returns all relevant information regarding the coupon & pool

        :rtype: dict
        """
        response = requests.get(self.url).json()
        basic_info = response['result'][0]['payload']['draw']['regCloseDescription']
        closing_time = response['result'][0]['payload']['draw']['regCloseTime']
        turnover = int(response['result'][0]['payload']
                       ['draw']['currentNetSale'].split(",")[0])
        id_round = response['result'][0]['id'].split("_")[1]
        ord_rtp = 0.65
        pool_10 = turnover * 0.25 * ord_rtp
        pool_11 = turnover * 0.12 * ord_rtp
        pool_12 = turnover * 0.15 * ord_rtp
        est_pool_13 = turnover * 0.4 * ord_rtp + self.added_money
        if self.guaranteed_win > est_pool_13:
            pool_13 = self.guaranteed_win
        else:
            pool_13 = est_pool_13
        true_rtp = (pool_13 + pool_12 + pool_11 + pool_10) / turnover

        return {"information": basic_info, "closing-time": closing_time, "turnover": turnover,
                "id-round": id_round, "added-money": self.added_money, "guaranteed-win": self.guaranteed_win,
                "pool-[13]": int(pool_13), "pool-[12]": int(pool_12), "pool-[11]": int(pool_11), "pool-[10]": int(pool_10),
                "rtp": true_rtp,
                }

    def scrape_odds_svs(self):
        """
        Odds scraped from Svenska Spel

        :rtype: list of dicts
        """
        response = requests.get(self.url).json()
        odds = []
        for game in response['result'][0]['payload']['draw']['drawEvents']:
            home_team = game['match']['participants'][0]['name']
            away_team = game['match']['participants'][1]['name']
            try:
                ss_odds = [float(game['odds']['one'].replace(",", ".")), float(
                    game['odds']['x'].replace(",", ".")), float(game['odds']['two'].replace(",", "."))]
                odds.append(
                    {"match": home_team + ' v ' + away_team, "odds": ss_odds})
            except Exception as e:
                if 'odds' in str(e):
                    # failed to fetch the odds, appends [0.00, 0.00, 0.00] to clarify that the request was unsuccessful
                    # print(
                    #     f"Couldn't find the Svenska Spel odds for {home_team} v {away_team}")
                    odds.append({"match": home_team + ' v ' +
                                 away_team, "odds": [0.00, 0.00, 0.00]})
                else:
                    # unknown error, prints it and appends [0.00, 0.00, 0.00] to clarify that the request was unsuccessful
                    print_exc()

        return odds

    def scrape_odds_betfair(self):
        """
        Odds scraped from Betfair for improved accuracy

        :rtype: list of dicts
        """
        response = requests.get(self.url).json()
        betfair_odds = []

        date = response['result'][0]['payload']['draw']['regCloseTime'].split("T")[
            0]
        trading = betfairlightweight.APIClient(
            username=USERNAME,
            password=PASSWORD,
            app_key=APP_KEY,
            locale=LOCALE)

        trading.login_interactive()
        # if not trading.session_expired:
        #     print("---------------------------------------------------")
        #     print("Logged into Betfair...")
        #     print("---------------------------------------------------")

        for game in response['result'][0]['payload']['draw']['drawEvents']:
            # loops through every game, fetches the home and away team from Svenska Spel, finds the game
            # at Betfair and collects the odds
            # if unsuccessful, append [0.00, 0.00, 0.00] as odds for the game

            # USE thefuzz library
            home_team = game['match']['participants'][0]['name'] # + fuzz stuff
            away_team = game['match']['participants'][1]['name'] # + fuzz stuff
            text_query = f"{home_team} v {away_team}"

            # the games are almost always [>99%] taking place during the same day, hence timedelta = 1
            # increase timedelta if necessary
            market_catalogues = trading.betting.list_market_catalogue(
                filter=market_filter(text_query=text_query, market_start_time={"from": date, "to": datetime.strftime(
                    datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1), "%Y-%m-%d")}),
                max_results=1000,
            )

            # accounts for the case where the game couldn't be found at Betfair
            if not market_catalogues:
                # print(
                #     f"Couldn't find the Betfair odds for {home_team} v {away_team}")
                betfair_odds.append(
                    {"match": home_team + ' v ' + away_team, "odds": [0.00, 0.00, 0.00]})
                continue

            market_id = None
            for obj in market_catalogues:
                if obj.market_name == 'Match Odds':
                    market_id = obj.market_id
                    break

            try:
                market_book = trading.betting.list_market_book(
                    market_ids=[market_id])[0]
                market_catalogue = trading.betting.list_market_catalogue(
                    filter=market_filter(market_ids=[market_id]),
                    market_projection=["RUNNER_DESCRIPTION", "RUNNER_METADATA"])[0]

                price_filter = betfairlightweight.filters.price_projection(
                    price_data=['EX_BEST_OFFERS'])

                outcome_odds = []
                for run_cat in market_catalogue.runners:
                    # loops through and computes the true/average odds for all outcomes, appends to list outcome_odds
                    sel_id = run_cat.selection_id
                    runner_book_ex = trading.betting.list_runner_book(
                        market_id=market_id,
                        selection_id=sel_id,
                        price_projection=price_filter)[0].runners[0].ex
                    back_prices = runner_book_ex.available_to_back
                    lay_prices = runner_book_ex.available_to_lay
                    min_lay = lay_prices[0].price
                    max_back = back_prices[0].price
                    true_odds = (min_lay + max_back) / 2
                    outcome_odds.append(round(true_odds, 3))
            except:
                # unknown error, appends [0.00, 0.00, 0.00] to clarify that the request was unsuccessful
                print_exc()
                betfair_odds.append(
                    {"match": home_team + ' v ' + away_team, "odds": [0.00, 0.00, 0.00]})

            # in this case everything went as expected, appends the information to the betfair_odds list
            betfair_odds.append(
                {"match": home_team + ' v ' + away_team, "odds": [outcome_odds[0], outcome_odds[2], outcome_odds[1]]})

        trading.logout()
        # if trading.session_expired:
        #     print("---------------------------------------------------")
        #     print("Logged out of Betfair...")
        #     print("---------------------------------------------------")

        return betfair_odds

    def scrape_procent(self):
        """
        Stryktips-percentages scraped from Svenska Spel

        :rtype: list of dicts
        """
        procent = []
        response = requests.get(self.url).json()
        for game in response['result'][0]['payload']['draw']['drawEvents']:
            home_team = game['match']['participants'][0]['name']
            away_team = game['match']['participants'][1]['name']
            spelprocent = [float(game['betMetrics']['values'][0]['distribution']['distribution'].replace(",", ".")) / 100,
                           float(game['betMetrics']['values'][1]['distribution']
                                 ['distribution'].replace(",", ".")) / 100,
                           float(game['betMetrics']['values'][2]['distribution']['distribution'].replace(",", ".")) / 100]
            procent.append(
                {"match": home_team + ' v ' + away_team, "spelprocent": spelprocent})

        return procent

    def ev_games(self, betfair=False):
        """
        Odds compared to percentages to obtain a picture of where the +EV is

        Set betfair = True if odds from betfair are to be used
        :rtype: list of dicts
        """
        ev = []
        if betfair:
            odds = self.scrape_odds_betfair()
        else:
            odds = self.scrape_odds_svs()
        spelprocent = self.scrape_procent()
        assert len(odds) == len(
            spelprocent), "length of list odds and list procent are unequal"
        for game_nr in range(len(odds)):
            try:
                ev_game = []
                rtp = return_to_player_3way(
                    odds[game_nr]['odds'][0], odds[game_nr]['odds'][1], odds[game_nr]['odds'][2])
                for outcome_nr in range(3):
                    outcome_ev = round(((1 / odds[game_nr]['odds'][outcome_nr]) * rtp) /
                                       spelprocent[game_nr]['spelprocent'][outcome_nr], 4)
                    ev_game.append(outcome_ev)
                ev.append({"match": odds[game_nr]['match'], "ev": ev_game})
            except ZeroDivisionError:
                ev.append(
                    {"match": odds[game_nr]['match'], "ev": [0.00, 0.00, 0.00]})
            except Exception as e:
                print(
                    f"An unknown error occurred when computing the EV for {odds[game_nr]['match']}")
                print_exc()

        return ev

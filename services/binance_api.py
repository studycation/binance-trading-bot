from binance.client import Client
from config.config import API_KEY, API_SECRET

class BinanceAPI:
    def __init__(self):
        self.client = Client(API_KEY, API_SECRET)

    def get_exchange_info(self):
        """모든 선물 종목의 거래 정보를 가져옴"""
        return self.client.futures_exchange_info()

    def get_24h_ticker(self, symbol):
        """24시간 동안의 가격 변동 데이터를 가져옴"""
        return self.client.futures_ticker(symbol=symbol)

    def get_min_trade_quantity(self, symbol):
        """해당 심볼의 최소 거래 가능 수량과 precision(소수점 자리수) 반환"""
        exchange_info = self.get_exchange_info()
        for s in exchange_info["symbols"]:
            if s["symbol"] == symbol:
                for f in s["filters"]:
                    if f["filterType"] == "LOT_SIZE":
                        min_qty = float(f["minQty"])
                        precision = self.get_precision(f["minQty"])
                        return min_qty, precision
        return None, None  # 최소 거래 수량을 찾지 못한 경우

    def get_precision(self, min_qty_str):
        """LOT_SIZE에서 허용하는 소수점 자리수 반환"""
        min_qty_str = str(min_qty_str)
        if "1" in min_qty_str:
            return max(0, len(min_qty_str.split(".")[-1].rstrip("0")))
        return 0  # 정수 단위 거래일 경우 (소수점 없음)

    def set_isolated_margin(self, symbol, leverage=15):
        """Isolated 모드로 설정 및 레버리지 적용 (이미 설정되어 있으면 변경하지 않음)"""
        try:
            # 현재 마진 모드 조회
            account_info = self.client.futures_account()
            for position in account_info['positions']:
                if position['symbol'] == symbol:
                    if position['isolated']:
                        return  

            # 마진 모드 변경 (필요한 경우만)
            self.client.futures_change_margin_type(symbol=symbol, marginType="ISOLATED")
        except Exception as e:
            if "No need to change margin type" in str(e):
                pass  # 이미 설정된 경우 오류 무시
            else:
                raise e  # 다른 오류는 그대로 발생시키기

        # 레버리지 설정 (항상 적용)
        self.client.futures_change_leverage(symbol=symbol, leverage=leverage)

    def place_short_order(self, symbol, quantity, entry_price):
        """숏 포지션 진입 (매도 주문), 최소 주문 금액(5 USDT) 미만이면 수량 조정"""
        min_qty, precision = self.get_min_trade_quantity(symbol)

        if precision is not None:
            quantity = round(quantity, precision)

        # 최소 주문 금액(5 USDT) 충족 검사
        min_order_value = 5  # Binance 최소 주문 금액
        if quantity * entry_price < min_order_value:
            quantity = min_order_value / entry_price
            quantity = round(quantity, precision)

        order = self.client.futures_create_order(
            symbol=symbol,
            side="SELL",  # 숏 포지션 진입
            type="MARKET",
            quantity=quantity
        )
        return order

    def place_tp_order(self, symbol, quantity, entry_price, leverage=15, target_profit=1.6):
        """PnL 기준 1.6% 수익 도달 시 자동 매도 주문 실행"""

        # PnL(수익률) 기준 목표가 계산
        target_pnl = target_profit / 100  # 예: 1.6% → 0.016
        target_price = entry_price * (1 - (target_pnl / leverage))  # PnL 기준 목표가 조정

        # 최소 주문 수량 및 Precision 확인
        min_qty, precision = self.get_min_trade_quantity(symbol)
        price_precision = self.get_price_precision(symbol)

        if precision is not None:
            quantity = round(quantity, precision)  # 주문 수량을 허용된 Precision으로 반올림

        if price_precision is not None:
            target_price = round(target_price, price_precision)  # 목표 가격도 허용된 Precision으로 반올림

        # 최소 주문 금액(5 USDT) 충족 검사
        min_order_value = 5  # Binance 최소 주문 금액
        if quantity * target_price < min_order_value:
            quantity = min_order_value / target_price
            quantity = round(quantity, precision)

        order = self.client.futures_create_order(
            symbol=symbol,
            side="BUY",  # 숏 포지션이므로 자동 매도 주문 (BUY)
            type="TAKE_PROFIT_MARKET",  # 목표가 도달 시 시장가 매도
            quantity=quantity,
            stopPrice=target_price,  # 목표가 반올림 적용
            timeInForce="GTC"
        )
        return order

    def get_price_precision(self, symbol):
        """Binance에서 허용하는 가격 Precision을 가져오는 함수"""
        exchange_info = self.get_exchange_info()
        for s in exchange_info["symbols"]:
            if s["symbol"] == symbol:
                for f in s["filters"]:
                    if f["filterType"] == "PRICE_FILTER":
                        return len(str(f["tickSize"]).rstrip('0').split('.')[-1])  # 허용된 소수점 자리수 반환
        return None



# TODO : 진입과 동시에 목표가에 LIMIT 익절 주문 넣는 방식으로 수정하기
# import math
# from typing import Tuple, Optional
# from binance.client import Client
# from config.config import API_KEY, API_SECRET


# class BinanceAPI:
#     """
#     USDⓈ-M 선물용 헬퍼
#     - 진입: 최소 명목 5 USDT 이상이 되도록 stepSize 기반 보정
#     - TP: LIMIT(reduceOnly=True)로 바로 예약. 명목 < 5USDT면 TP-MARKET(closePosition=True)로 폴백
#     - 가격/수량은 tickSize/stepSize 정합을 엄수
#     """

#     def __init__(self):
#         self.client = Client(API_KEY, API_SECRET)

#     # -------------------- Exchange Info / Filters -------------------- #
#     def get_exchange_info(self):
#         return self.client.futures_exchange_info()

#     def _symbol_filters(self, symbol: str):
#         info = self.get_exchange_info()
#         for s in info["symbols"]:
#             if s["symbol"] == symbol:
#                 return s["filters"]
#         raise ValueError(f"Symbol not found in exchangeInfo: {symbol}")

#     def _step_size(self, symbol: str) -> float:
#         for f in self._symbol_filters(symbol):
#             if f["filterType"] == "LOT_SIZE":
#                 return float(f["stepSize"])
#         return 1.0

#     def _tick_size(self, symbol: str) -> float:
#         for f in self._symbol_filters(symbol):
#             if f["filterType"] == "PRICE_FILTER":
#                 return float(f["tickSize"])
#         return 1.0

#     @staticmethod
#     def _ceil_to_step(x: float, step: float) -> float:
#         return math.ceil(x / step) * step

#     @staticmethod
#     def _floor_to_step(x: float, step: float) -> float:
#         return math.floor(x / step) * step

#     # (하위 호환: 예전 코드가 쓰던 메서드들)
#     def get_min_trade_quantity(self, symbol) -> Tuple[Optional[float], Optional[int]]:
#         """LOT_SIZE에서 minQty와 precision 추정(하위 호환)"""
#         min_qty = None
#         for f in self._symbol_filters(symbol):
#             if f["filterType"] == "LOT_SIZE":
#                 min_qty = float(f["minQty"])
#                 step = float(f["stepSize"])
#                 # stepSize의 소수 자릿수 = precision
#                 precision = 0
#                 if "." in f["stepSize"]:
#                     precision = len(f["stepSize"].rstrip("0").split(".")[-1])
#                 return min_qty, precision
#         return None, None

#     def get_price_precision(self, symbol) -> Optional[int]:
#         for f in self._symbol_filters(symbol):
#             if f["filterType"] == "PRICE_FILTER":
#                 tick = f["tickSize"]
#                 if "." in tick:
#                     return len(tick.rstrip("0").split(".")[-1])
#                 return 0
#         return None

#     # -------------------- Market Data -------------------- #
#     def get_24h_ticker(self, symbol):
#         return self.client.futures_ticker(symbol=symbol)

#     # -------------------- Margin / Leverage -------------------- #
#     def set_isolated_margin(self, symbol, leverage=15):
#         try:
#             self.client.futures_change_margin_type(symbol=symbol, marginType="ISOLATED")
#         except Exception as e:
#             if "No need to change margin type" not in str(e):
#                 raise
#         self.client.futures_change_leverage(symbol=symbol, leverage=leverage)

#     # -------------------- Entry Orders -------------------- #
#     def place_long_order(self, symbol: str, quantity: float, entry_price: float):
#         """
#         롱 진입(시장가 BUY)
#         - 최소 명목 5USDT 미만이면 step 기준 '올림'하여 보정
#         - 반환: (order_resp, actual_qty)
#         """
#         step = self._step_size(symbol)
#         min_notional = 5.0

#         if quantity * entry_price < min_notional:
#             need = min_notional / entry_price
#             quantity = self._ceil_to_step(need, step)
#         else:
#             quantity = self._floor_to_step(quantity, step)

#         order = self.client.futures_create_order(
#             symbol=symbol,
#             side="BUY",
#             type="MARKET",
#             quantity=quantity
#         )
#         return order, quantity

#     def place_short_order(self, symbol: str, quantity: float, entry_price: float):
#         """
#         숏 진입(시장가 SELL) – 위와 동일 로직
#         """
#         step = self._step_size(symbol)
#         min_notional = 5.0

#         if quantity * entry_price < min_notional:
#             need = min_notional / entry_price
#             quantity = self._ceil_to_step(need, step)
#         else:
#             quantity = self._floor_to_step(quantity, step)

#         order = self.client.futures_create_order(
#             symbol=symbol,
#             side="SELL",
#             type="MARKET",
#             quantity=quantity
#         )
#         return order, quantity

#     # -------------------- TP Price 계산 -------------------- #
#     @staticmethod
#     def _tp_target_price(entry_price: float, leverage: int, target_profit_pct: float, side: str) -> float:
#         """
#         PnL% 기준 목표가 계산 (퍼센트는 계정 기준, 레버리지 반영)
#         side: 'LONG' or 'SHORT'
#         """
#         pnl = target_profit_pct / 100.0
#         if side.upper() == "LONG":
#             return entry_price * (1.0 + pnl / float(leverage))
#         else:  # SHORT
#             return entry_price * (1.0 - pnl / float(leverage))

#     # -------------------- TP as LIMIT (reduceOnly) -------------------- #
#     def place_tp_limit_close_all(self, symbol: str, side: str, position_qty: float,
#                                  entry_price: float, leverage: int = 15,
#                                  target_profit: float = 1.6):
#         """
#         진입 직후 LIMIT TP 예약(전량 청산 가정)
#         - LONG 포지션: SELL-LIMIT(reduceOnly=True)
#         - SHORT 포지션: BUY-LIMIT(reduceOnly=True)
#         - 명목 < 5USDT면 TP-MARKET(closePosition=True)로 폴백
#         """
#         step = self._step_size(symbol)
#         tick = self._tick_size(symbol)

#         # 목표가
#         raw_price = self._tp_target_price(entry_price, leverage, target_profit, side)

#         # 방향별 안전한 라운딩:
#         #   LONG의 익절 SELL-LIMIT은 살짝 '위로'(= ceil) 라운딩
#         #   SHORT의 익절 BUY-LIMIT은 살짝 '아래로'(= floor) 라운딩
#         if side.upper() == "LONG":
#             price = self._ceil_to_step(raw_price, tick)
#             order_side = "SELL"
#         else:  # SHORT
#             price = self._floor_to_step(raw_price, tick)
#             order_side = "BUY"

#         qty = self._floor_to_step(abs(position_qty), step)  # 보유 수량 초과 금지
#         notional = qty * price

#         # LIMIT + reduceOnly에선 일반적으로 최소 명목 5USDT 규칙이 그대로 적용됨
#         # 숏 TP(낮은 가격) 등으로 5 미만이 되면 안전하게 MARKET TP로 폴백
#         if notional < 5.0:
#             return self.place_tp_close_all_market(symbol, entry_price, leverage, target_profit, side)

#         return self.client.futures_create_order(
#             symbol=symbol,
#             side=order_side,
#             type="LIMIT",
#             timeInForce="GTC",
#             price=f"{price:.20f}",
#             quantity=qty,
#             reduceOnly=True  # 포지션만 줄임(추가 진입 방지)
#         )

#     # -------------------- TP as MARKET (폴백/옵션) -------------------- #
#     def place_tp_close_all_market(self, symbol: str, entry_price: float,
#                                   leverage: int, target_profit: float, side: str):
#         """
#         LIMIT로 5USDT 미만이 되는 경우를 위한 폴백:
#         TAKE_PROFIT_MARKET + closePosition=True
#         """
#         tick = self._tick_size(symbol)
#         raw = self._tp_target_price(entry_price, leverage, target_profit, side)

#         # MARKET TP의 stopPrice 라운딩: 트리거 조건을 확실히 만족하도록
#         stop_price = self._floor_to_step(raw, tick) if side.upper() == "SHORT" else self._ceil_to_step(raw, tick)

#         order_side = "SELL" if side.upper() == "LONG" else "BUY"

#         return self.client.futures_create_order(
#             symbol=symbol,
#             side=order_side,
#             type="TAKE_PROFIT_MARKET",
#             stopPrice=f"{stop_price:.20f}",
#             closePosition=True,      # 전량 청산
#             workingType="MARK_PRICE" # 마크가격 기준 트리거 권장
#         )

#     # -------------------- (선택) SL -------------------- #
#     def place_sl_close_all_market(self, symbol: str, entry_price: float,
#                                   leverage: int = 15, stop_loss_pct: float = 1.0, side: str = "LONG"):
#         """
#         전량 손절(시장가). LONG이면 SELL, SHORT이면 BUY.
#         """
#         tick = self._tick_size(symbol)
#         sl = stop_loss_pct / 100.0
#         if side.upper() == "LONG":
#             # LONG 손절: entry * (1 - sl/leverage) -> stopPrice는 '아래'로 절삭
#             stop_price = entry_price * (1.0 - sl / float(leverage))
#             stop_price = self._floor_to_step(stop_price, tick)
#             order_side = "SELL"
#         else:
#             # SHORT 손절: entry * (1 + sl/leverage) -> stopPrice는 '위'로 올림
#             stop_price = entry_price * (1.0 + sl / float(leverage))
#             stop_price = self._ceil_to_step(stop_price, tick)
#             order_side = "BUY"

#         return self.client.futures_create_order(
#             symbol=symbol,
#             side=order_side,
#             type="STOP_MARKET",
#             stopPrice=f"{stop_price:.20f}",
#             closePosition=True,
#             workingType="MARK_PRICE"
#         )



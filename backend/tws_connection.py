# backend/tws_connection.py

import asyncio
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from datetime import datetime
import time
import threading
import queue

from portfolio_manager import portfolio_manager
from utils import get_contract_description
from config import settings

class RequestGate:
    def __init__(self, requests_per_second=45):
        self.interval = 1.0 / requests_per_second
        self.last_request_time = 0
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            now = time.time()
            elapsed = now - self.last_request_time
            if elapsed < self.interval:
                time.sleep(self.interval - elapsed)
            self.last_request_time = time.time()

class IBKRApp(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self, self)
        self.next_req_id = 0; self.pnl_req_map = {}; self.mkt_data_req_map = {}; self._positions_being_updated = set(); self.und_price_cache = {}; self.request_containers = {}
        self.request_queue = queue.Queue()
        self.gate = RequestGate(45)

    def request_worker(self):
        print("--> Request worker started.")
        while True:
            try:
                conId, account = self.request_queue.get()
                
                pnlReqId = self.next_req_id; self.next_req_id += 1
                self.pnl_req_map[pnlReqId] = conId
                self.reqPnLSingle(pnlReqId, account, "", conId)
                self.gate.wait()

                c = Contract(); c.conId = conId; c.exchange = "SMART"; c.currency = "USD"
                mktReqId = self.next_req_id; self.next_req_id += 1
                self.mkt_data_req_map[mktReqId] = conId
                self.reqMktData(mktReqId, c, "", False, False, [])
                self.gate.wait()
            except Exception as e:
                print(f"Error in request worker: {e}")

    def run(self):
        print("--> TWS message loop starting. Starting request worker thread...")
        worker_thread = threading.Thread(target=self.request_worker, daemon=True)
        worker_thread.start()
        super().run() # This starts the blocking message loop

    # ... (The rest of the file is unchanged. All other methods are the same as the last version.)
    def error(self, reqId, errorCode, errorString):
        container = self.request_containers.get(reqId)
        if container:
            if errorCode in [2104, 2106, 2108, 2158, 2150, 2107]: return
            container['error'] = f"Error {errorCode}: {errorString}"
            if 'event' in container: container['loop'].call_soon_threadsafe(container['event'].set)
        if errorCode in [2104, 2106, 2108, 2158, 2150]: return
        print(f"TWS Error (reqId {reqId}): {errorCode} - {errorString}")
    def nextValidId(self, orderId: int):
        super().nextValidId(orderId); self.reqMarketDataType(1); self.next_req_id = orderId; self.reqPositions(); self.req_und_price("SPY"); self.req_und_price("QQQ")
    def req_und_price(self, symbol):
        contract = Contract(); contract.symbol = symbol; contract.secType = "STK"; contract.currency = "USD"; contract.exchange = "SMART"
        reqId = self.next_req_id; self.request_containers[reqId] = {'type': 'und_price', 'symbol': symbol}; self.reqMktData(reqId, contract, "", False, False, []); self.next_req_id += 1
    def tickPrice(self, reqId, tickType, price, attrib):
        super().tickPrice(reqId, tickType, price, attrib)
        container = self.request_containers.get(reqId)
        if container:
            if container.get('type') == 'und_price' and tickType in [4, 6, 9]:
                self.und_price_cache[container['symbol']] = price
            elif container.get('type') == 'option_data':
                if tickType == 1: container['data']['bid'] = price
                if tickType == 2: container['data']['ask'] = price
                if container.get('event') and container.get('data', {}).get('bid') is not None and container.get('data', {}).get('ask') is not None and container.get('data', {}).get('delta') is not None:
                    container['loop'].call_soon_threadsafe(container['event'].set)
    def contractDetails(self, reqId, contractDetails):
        container = self.request_containers.get(reqId)
        if container: container['contract'] = contractDetails.contract; 
        if 'event' in container: container['loop'].call_soon_threadsafe(container['event'].set)
    def contractDetailsEnd(self, reqId):
        container = self.request_containers.get(reqId)
        if container and 'event' in container and 'contract' not in container: container['loop'].call_soon_threadsafe(container['event'].set)
    def historicalData(self, reqId, bar):
        container = self.request_containers.get(reqId)
        if container and container.get('type') == 'hist_vol': container['data'].append(bar.close)
    def historicalDataEnd(self, reqId, start, end):
        container = self.request_containers.get(reqId)
        if container and container.get('type') == 'hist_vol': container['loop'].call_soon_threadsafe(container['event'].set)
    async def resolve_contract(self, contract: Contract) -> Contract:
        loop = asyncio.get_event_loop(); req_id = self.next_req_id; self.next_req_id += 1
        container = {'loop': loop, 'event': asyncio.Event()}; self.request_containers[req_id] = container
        self.reqContractDetails(req_id, contract)
        await container['event'].wait()
        response_container = self.request_containers.pop(req_id)
        if 'error' in response_container: raise Exception(response_container['error'])
        if 'contract' not in response_container: raise Exception("Contract not found")
        return response_container['contract']
    async def fetch_option_data(self, contract: Contract) -> dict:
        loop = asyncio.get_event_loop()
        try: full_contract = await self.resolve_contract(contract)
        except Exception as e: print(f"Could not resolve contract for {contract.symbol}: {e}"); return {}
        req_id_mkt = self.next_req_id; self.next_req_id += 1; container = { 'loop': loop, 'event': asyncio.Event(), 'type': 'option_data', 'contract': full_contract, 'data': {} }; self.request_containers[req_id_mkt] = container
        await loop.run_in_executor(None, lambda: self.reqMktData(req_id_mkt, full_contract, "100,101,104,106", False, False, []))
        try: await asyncio.wait_for(container['event'].wait(), timeout=15)
        except asyncio.TimeoutError: pass
        finally:
            await loop.run_in_executor(None, lambda: self.cancelMktData(req_id_mkt))
            response = {"contract": container.get("contract"),"data": container.get("data", {})}
            if req_id_mkt in self.request_containers: del self.request_containers[req_id_mkt]
            return response
    async def fetch_historical_volatility(self, contract: Contract) -> list:
        loop = asyncio.get_event_loop(); req_id = self.next_req_id; self.next_req_id += 1; container = { 'loop': loop, 'event': asyncio.Event(), 'type': 'hist_vol', 'data': [] }; self.request_containers[req_id] = container; query_time = datetime.now().strftime("%Y%m%d %H:%M:%S")
        await loop.run_in_executor(None, lambda: self.reqHistoricalData(req_id, contract, query_time, "1 Y", "1 day", "HISTORICAL_VOLATILITY", 0, 1, False, []))
        try: await asyncio.wait_for(container['event'].wait(), timeout=20)
        except asyncio.TimeoutError: print(f"Timed out fetching historical volatility for {contract.symbol}")
        finally:
            data = container.get('data', [])
            if req_id in self.request_containers: del self.request_containers[req_id]
            return data
    def tickOptionComputation(self, reqId, tickType, tickAttrib, impliedVol, delta, optPrice, pvDividend, gamma, vega, theta, undPrice):
        conId = self.mkt_data_req_map.get(reqId)
        if conId:
            p = portfolio_manager.get_position(conId)
            if p:
                if undPrice is not None and undPrice > 0: p['greeks']['undPrice'] = undPrice
                if ' C' in p.get('description','') or ' P' in p.get('description',''):
                    if tickType in [13, 84]:
                        p['greeks']['iv'] = impliedVol if impliedVol is not None and impliedVol > 0 and abs(impliedVol) < 1e9 else p['greeks']['iv']
                        p['greeks']['delta'] = delta if delta is not None and abs(delta) < 1e9 else p['greeks']['delta']
                        p['greeks']['gamma'] = gamma if gamma is not None and abs(gamma) < 1e9 else p['greeks']['gamma']
                        p['greeks']['vega'] = vega if vega is not None and abs(vega) < 1e9 else p['greeks']['vega']
                        p['greeks']['theta'] = theta if theta is not None and abs(theta) < 1e9 else p['greeks']['theta']
                portfolio_manager.update_position(conId, p)
        container = self.request_containers.get(reqId)
        if container and container.get('type') == 'option_data':
            if tickType in [13, 84]:
                data = container['data']
                data.update({'iv': impliedVol, 'delta': delta, 'gamma': gamma, 'vega': vega, 'theta': theta, 'undPrice': undPrice})
                if container.get('event') and data.get('bid') is not None and data.get('ask') is not None:
                    container['loop'].call_soon_threadsafe(container['event'].set)
    def position(self, account: str, contract: Contract, position: float, avgCost: float):
        if contract.symbol in settings.TWS_IGNORE_LIST: print(f"--> Ignoring position based on symbol: {contract.symbol}"); return
        super().position(account, contract, position, avgCost)
        conId = contract.conId; self._positions_being_updated.add(conId)
        cost_basis = position * avgCost
        position_data = { "conId":conId, "description":get_contract_description(contract), "position":position, "avgCost":avgCost, "costBasis":cost_basis, "marketValue":cost_basis, "pnl":{"daily":0.0,"unrealized":0.0}, "greeks":{"delta":0.0,"gamma":0.0,"vega":0.0,"theta":0.0,"iv":0.0,"undPrice":None}, "status":"Live" }
        portfolio_manager.update_position(conId, position_data)
        self.request_queue.put((conId, account))
    def positionEnd(self):
        super().positionEnd(); all_known_conIds={p['conId'] for p in portfolio_manager.get_all_positions()}; stale_conIds=all_known_conIds-self._positions_being_updated
        for conId in stale_conIds: portfolio_manager.remove_position(conId)
        self._positions_being_updated.clear(); print("--> Portfolio update complete.")
    def pnlSingle(self, reqId, pos, dailyPnL, unrealizedPnL, realizedPnL, value):
        super().pnlSingle(reqId,pos,dailyPnL,unrealizedPnL,realizedPnL,value); conId=self.pnl_req_map.get(reqId);
        if not conId: return
        p=portfolio_manager.get_position(conId);
        if p:
            if dailyPnL is not None and dailyPnL!=float('inf') and abs(dailyPnL)<1e9: p['pnl']['daily']=dailyPnL
            if unrealizedPnL is not None and unrealizedPnL!=float('inf') and abs(unrealizedPnL)<1e9: p['pnl']['unrealized']=unrealizedPnL
            if value is not None and value!=float('inf') and abs(value)<1e9: p['marketValue']=value
            portfolio_manager.update_position(conId,p)
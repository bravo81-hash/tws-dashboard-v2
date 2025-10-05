# backend/tws_connection.py (fully corrected and complete)

import asyncio
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
import threading
import time

from portfolio_manager import portfolio_manager
from utils import get_contract_description

class IBKRApp(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self, self)
        self.next_req_id = 0
        self.pnl_req_map = {}
        self.mkt_data_req_map = {}
        self._positions_being_updated = set()
        self.und_price_cache = {}
        self.request_containers = {}

    def error(self, reqId, errorCode, errorString):
        if reqId in self.request_containers:
            container = self.request_containers[reqId]
            if errorCode != 200:
                container['error'] = f"Error {errorCode}: {errorString}"
            if 'event' in container:
                container['loop'].call_soon_threadsafe(container['event'].set)

        if errorCode in [2104, 2106, 2108, 2158, 2150]:
            return
        print(f"TWS Error (reqId {reqId}): {errorCode} - {errorString}")

    def nextValidId(self, orderId: int):
        super().nextValidId(orderId)
        self.next_req_id = orderId
        self.reqPositions()
        self.req_und_price("SPY")
        self.req_und_price("QQQ")
    
    def req_und_price(self, symbol):
        contract = Contract()
        contract.symbol = symbol; contract.secType = "STK"; contract.currency = "USD"; contract.exchange = "SMART"
        reqId = self.next_req_id
        self.request_containers[reqId] = {'type': 'und_price', 'symbol': symbol}
        self.reqMktData(reqId, contract, "", False, False, [])
        self.next_req_id += 1

    def tickPrice(self, reqId, tickType, price, attrib):
        super().tickPrice(reqId, tickType, price, attrib)
        if reqId in self.request_containers:
            container = self.request_containers[reqId]
            if container.get('type') == 'und_price':
                if tickType in [4, 6, 9]:
                    self.und_price_cache[container['symbol']] = price
            
            if container.get('type') == 'option_data':
                if tickType == 1: container['data']['bid'] = price
                if tickType == 2: container['data']['ask'] = price
                if container.get('event') and container.get('data', {}).get('bid') is not None and container.get('data', {}).get('ask') is not None:
                     if container.get('data', {}).get('delta') is not None:
                        container['loop'].call_soon_threadsafe(container['event'].set)

    def contractDetails(self, reqId, contractDetails):
        if reqId in self.request_containers:
            container = self.request_containers[reqId]
            container['contract'] = contractDetails.contract
            if 'event' in container:
                container['loop'].call_soon_threadsafe(container['event'].set)

    def contractDetailsEnd(self, reqId):
        if reqId in self.request_containers:
            container = self.request_containers[reqId]
            if 'event' in container and 'contract' not in container:
                container['loop'].call_soon_threadsafe(container['event'].set)
    
    async def resolve_contract(self, req_id: int, contract: Contract) -> Contract:
        loop = asyncio.get_event_loop()
        event = asyncio.Event()
        result_container = {}
        error_container = {}

        original_contractDetails_handler = self.contractDetails
        original_contractDetailsEnd_handler = self.contractDetailsEnd
        original_error_handler = self.error

        def contractDetails(reqId, contractDetails):
            if reqId == req_id:
                result_container['contract'] = contractDetails.contract
            original_contractDetails_handler(reqId, contractDetails)

        def contractDetailsEnd(reqId):
            if reqId == req_id:
                loop.call_soon_threadsafe(event.set)
            original_contractDetailsEnd_handler(reqId)

        def error_handler(self, reqId, errorCode, errorString):
            if reqId == req_id and errorCode not in [2104, 2106, 2108, 2158]:
                error_container['error'] = f"Error {errorCode}: {errorString}"
                loop.call_soon_threadsafe(event.set)
            original_error_handler(reqId, errorCode, errorString)

        self.contractDetails = contractDetails
        self.contractDetailsEnd = contractDetailsEnd
        self.error = error_handler.__get__(self, IBKRApp)
        
        self.reqContractDetails(req_id, contract)
        await event.wait()

        self.contractDetails = original_contractDetails_handler
        self.contractDetailsEnd = original_contractDetailsEnd_handler
        self.error = original_error_handler

        if 'error' in error_container:
            raise Exception(error_container['error'])
        if 'contract' not in result_container:
            raise Exception("Contract not found")
            
        return result_container['contract']

    async def fetch_option_data(self, contract: Contract) -> dict:
        loop = asyncio.get_event_loop()
        event = asyncio.Event()
        
        req_id_cd = self.next_req_id; self.next_req_id += 1
        try:
            full_contract = await self.resolve_contract(req_id_cd, contract)
        except Exception:
            return {}
        
        req_id_mkt = self.next_req_id; self.next_req_id += 1
        container = { 'loop': loop, 'event': event, 'type': 'option_data', 'contract': full_contract, 'data': {} }
        self.request_containers[req_id_mkt] = container
        self.reqMktData(req_id_mkt, full_contract, "100,101,104,106", False, False, [])

        try:
            await asyncio.wait_for(event.wait(), timeout=15)
            return container
        except asyncio.TimeoutError:
            return container
        finally:
            self.cancelMktData(req_id_mkt)
            if req_id_mkt in self.request_containers:
                del self.request_containers[req_id_mkt]

    def tickOptionComputation(self, reqId, tickType, tickAttrib, impliedVol, delta, optPrice, pvDividend, gamma, vega, theta, undPrice):
        if reqId in self.mkt_data_req_map:
            conId=self.mkt_data_req_map.get(reqId);
            if not conId: return
            p=portfolio_manager.get_position(conId);
            if not p: return
            if undPrice is not None and undPrice > 0: p['greeks']['undPrice']=undPrice
            if p.get('description','').count(' C') or p.get('description','').count(' P'):
                if tickType==13:
                    if impliedVol is not None and impliedVol > 0 and abs(impliedVol)<1e9: p['greeks']['iv']=impliedVol
                    if delta is not None and abs(delta)<1e9: p['greeks']['delta']=delta
                    if gamma is not None and abs(gamma)<1e9: p['greeks']['gamma']=gamma
                    if vega is not None and abs(vega)<1e9: p['greeks']['vega']=vega
                    if theta is not None and abs(theta)<1e9: p['greeks']['theta']=theta
            portfolio_manager.update_position(conId, p)

        if reqId in self.request_containers:
            container = self.request_containers[reqId]
            if container.get('type') == 'option_data':
                if tickType in [13, 84]:
                    data = container['data']
                    data['iv'] = impliedVol; data['delta'] = delta; data['gamma'] = gamma; data['vega'] = vega; data['theta'] = theta; data['undPrice'] = undPrice
                    if container.get('event') and data.get('bid') is not None and data.get('ask') is not None:
                        container['loop'].call_soon_threadsafe(container['event'].set)
    
    # --- Paste your existing position, positionEnd, and pnlSingle methods here ---
    def position(self, account: str, contract: Contract, position: float, avgCost: float):
        super().position(account, contract, position, avgCost); conId=contract.conId; self._positions_being_updated.add(conId); multiplier=1.0;
        if contract.secType=="OPT": multiplier=float(contract.multiplier) if contract.multiplier else 100.0
        cost_basis=avgCost*position*multiplier;
        position_data={"conId":conId,"description":get_contract_description(contract),"position":position,"avgCost":avgCost,"costBasis":cost_basis,"marketValue":cost_basis,"pnl":{"daily":0.0,"unrealized":0.0},"greeks":{"delta":0.0,"gamma":0.0,"vega":0.0,"theta":0.0,"iv":0.0,"undPrice":None},"status":"Live"};
        portfolio_manager.update_position(conId,position_data); pnlReqId=self.next_req_id; self.pnl_req_map[pnlReqId]=conId; self.reqPnLSingle(pnlReqId,account,"",conId); self.next_req_id+=1;
        if contract.secType in ["OPT","STK"]: mktReqId=self.next_req_id; self.mkt_data_req_map[mktReqId]=conId; self.reqMktData(mktReqId,contract,"",False,False,[]); self.next_req_id+=1

    def positionEnd(self):
        super().positionEnd(); all_known_conIds={p['conId'] for p in portfolio_manager.get_all_positions()}; stale_conIds=all_known_conIds-self._positions_being_updated;
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
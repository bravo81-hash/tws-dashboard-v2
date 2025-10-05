# backend/portfolio_manager.py

import threading

class PortfolioManager:
    def __init__(self):
        self._portfolio_data = {}
        self._lock = threading.Lock()

    def update_position(self, conId, position_data):
        """Safely update or add a new position to the portfolio."""
        with self._lock:
            self._portfolio_data[conId] = position_data

    def get_position(self, conId):
        """Safely retrieve a single position."""
        with self._lock:
            return self._portfolio_data.get(conId)

    def get_all_positions(self):
        """Safely retrieve all positions as a list."""
        with self._lock:
            return list(self._portfolio_data.values())

    def remove_position(self, conId):
        """Safely remove a position if it no longer exists."""
        with self._lock:
            if conId in self._portfolio_data:
                del self._portfolio_data[conId]

# Create a single, global instance of the manager that the whole application can share.
# This is a simple design pattern called a "singleton".
portfolio_manager = PortfolioManager()
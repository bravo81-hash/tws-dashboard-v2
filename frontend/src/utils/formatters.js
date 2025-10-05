/**
 * Formats a number as a USD currency string.
 * @param {number} value The number to format.
 * @param {boolean} showSign Whether to show a '+' for positive numbers.
 * @returns {string} The formatted currency string.
 */
// In frontend/src/utils/formatters.js

export function formatCurrency(value, showSign = false) {
  // ADDED: Safety check for excessively large numbers
  if (typeof value !== 'number' || isNaN(value) || Math.abs(value) > 1e12) {
    return 'N/A';
  }
  const options = {
    style: 'currency',
    currency: 'USD',
    signDisplay: showSign ? 'always' : 'auto',
  };
  return new Intl.NumberFormat('en-US', options).format(value);
}

/**
 * Formats a number to a fixed number of decimal places.
 * @param {number} value The number to format.
 * @param {number} digits The number of decimal places.
 * @returns {string} The formatted number string.
 */
export function formatNumber(value, digits = 2) {
  if (typeof value !== 'number' || isNaN(value)) {
    return 'N/A';
  }
  return value.toFixed(digits);
}
// In frontend/src/utils/formatters.js

export function formatGreek(value) {
  if (typeof value !== 'number' || isNaN(value)) {
    return '---';
  }
  return value.toFixed(4);
}
/**
 * Formats P&L as currency and adds a percentage of cost basis.
 * @param {number} pnl The profit or loss value.
 * @param {number} costBasis The cost basis for the position/combo.
 * @returns {string} The formatted string, e.g., "+$55.00 (1.2%)".
 */
export function formatPnlWithPercent(pnl, costBasis) {
  const pnlString = formatCurrency(pnl, true);

  // Calculate percentage, handle division by zero
  const pct = (costBasis && costBasis !== 0) ? (pnl / Math.abs(costBasis)) * 100 : 0;

  const pctString = ` (${pct.toFixed(1)}%)`;

  return `${pnlString}${pctString}`;
}
export function formatDate(dateString) {
  if (!dateString) return 'N/A';
  const date = new Date(dateString);
  return date.toLocaleDateString('en-US', {
    year: '2-digit',
    month: 'short',
    day: 'numeric',
  });
}
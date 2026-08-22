from eth_trend_v3.backtest import run

if __name__ == '__main__':
    report=run()
    print('Backtest completed. Horizons:', ', '.join(report['horizons']))

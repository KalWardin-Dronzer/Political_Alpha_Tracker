import logging
import json
import itertools
from src.cache_manager import CacheManager
from src.backtest import Backtester
import xgboost as xgb
from sklearn.metrics import accuracy_score
from sklearn.model_selection import TimeSeriesSplit
import numpy as np

logging.basicConfig(level=logging.WARNING)

def tune():
    cache = CacheManager()
    backtester = Backtester(cache)
    
    with cache._connect() as conn:
        rows = conn.execute("""
            SELECT a.scrip_code, a.date, c.cin
            FROM announcements a
            JOIN companies c ON a.scrip_code = c.scrip_code
            WHERE a.is_contract = 1
              AND a.date >= date('now', '-5 years')
            ORDER BY a.date ASC
        """).fetchall()

    X = []
    y = []

    for row in rows:
        row = dict(row)
        cin = row.get("cin")
        if not cin:
            continue

        connections = backtester.graph.alpha_query(cin)
        alpha_score = connections[0]["alpha_score"] if connections else 0
        
        import random
        from datetime import datetime, timedelta
        
        # Consistent random seed for tuning
        random.seed(cin)
        materiality_pct = random.uniform(2.0, 15.0) 
        vol_z_score = random.uniform(-1.0, 5.0)
        election_mult = connections[0].get("election_multiplier", 1.0) if connections else 1.0

        event_date = row["date"]
        start = (datetime.strptime(event_date, "%Y-%m-%d") - timedelta(days=5)).strftime("%Y-%m-%d")
        end = (datetime.strptime(event_date, "%Y-%m-%d") + timedelta(days=100)).strftime("%Y-%m-%d")

        prices = backtester._get_price_history(row["scrip_code"], start, end)
        if prices is None:
            continue

        returns = backtester._compute_returns(prices, event_date, [90])
        if 90 not in returns:
            continue
        
        X.append([alpha_score, materiality_pct, vol_z_score, election_mult])
        y.append(1 if returns[90] > 0 else 0)

    X = np.array(X)
    y = np.array(y)
    
    tscv = TimeSeriesSplit(n_splits=3)
    
    max_depths = [2, 3, 4]
    etas = [0.01, 0.05, 0.1, 0.2]
    lambdas = [0.1, 1.0, 5.0]
    alphas = [0.0, 0.1, 1.0]
    boost_rounds = [30, 50, 100]
    
    best_acc = 0
    best_params = {}
    
    for md, e, lam, alp, br in itertools.product(max_depths, etas, lambdas, alphas, boost_rounds):
        params = {
            'objective': 'binary:logistic',
            'max_depth': md,
            'eta': e,
            'lambda': lam,
            'alpha': alp,
            'eval_metric': 'logloss'
        }
        
        accuracies = []
        for train_index, test_index in tscv.split(X):
            X_train, X_test = X[train_index], X[test_index]
            y_train, y_test = y[train_index], y[test_index]
            
            dtrain = xgb.DMatrix(X_train, label=y_train)
            dtest = xgb.DMatrix(X_test, label=y_test)
            
            model = xgb.train(params, dtrain, num_boost_round=br)
            preds = model.predict(dtest)
            pred_labels = [1 if p > 0.5 else 0 for p in preds]
            acc = accuracy_score(y_test, pred_labels)
            accuracies.append(acc)
            
        avg_acc = np.mean(accuracies)
        if avg_acc > best_acc:
            best_acc = avg_acc
            best_params = (md, e, lam, alp, br)
            print(f"New best: {avg_acc*100:.2f}% | md={md}, eta={e}, lam={lam}, alp={alp}, br={br}")

if __name__ == "__main__":
    tune()

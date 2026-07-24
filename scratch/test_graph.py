from src.cache_manager import CacheManager
from src.entity_resolver import EntityResolver
from src.graph_manager import GraphManager

cache = CacheManager()
entity = EntityResolver(cache)
entity.invalidate_caches()
res = entity.resolve_all_donors()
print(f"Donors resolved: {res['resolved']}")

graph = GraphManager(cache)
graph.build_from_cache()
graph.save()
print(graph.get_stats())

results = graph.alpha_query("L74899DL1960GOI003335")
print(f"Alpha query results: {results}")

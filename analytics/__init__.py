"""Graph network-analytics package (UC3/UC4 + criticality).

The query *bodies* are versioned under ``aql/`` and loaded/executed by
``lib.graph_queries``; the modules here expose the per-use-case Python API
(closure filter + reachability for UC3, reroute delta for UC4) that the offline
UC tests and the 06-05 live runners call.
"""

from mcp.server.fastmcp import FastMCP
import inspect

mcp = FastMCP('test')
print('sse_app signature:', inspect.signature(mcp.sse_app))
print('streamable_http_app signature:', inspect.signature(mcp.streamable_http_app))

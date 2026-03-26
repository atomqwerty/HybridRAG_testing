"""
Table Agent — Answers structured/spec questions using Pandas + LLM-generated code.

Workflow:
    1. Load a DataFrame from Neo4j Car nodes (model, battery, range, price, etc.)
    2. Ask LLM to generate Pandas code to answer the question.
    3. Execute the code safely.
    4. Format and return the result as a Markdown table.

Benefit: 100% precision on numbers — no hallucination.
"""
import re
import pandas as pd
from app.config import Config
from app.logger import setup_logger
from langchain_openai import ChatOpenAI

logger = setup_logger(__name__)


class TableAgent:
    def __init__(self):
        self._llm = None
        self._df_cache = None

    def _get_llm(self):
        if self._llm is None:
            self._llm = ChatOpenAI(
                api_key=Config.OPENAI_API_KEY,
                base_url=Config.OPENAI_BASE_URL,
                model=Config.OPENAI_MODEL,
                temperature=0
            )
        return self._llm

    def _load_dataframe(self) -> pd.DataFrame:
        """Loads Car node specs from Neo4j into a Pandas DataFrame (cached)."""
        if self._df_cache is not None:
            return self._df_cache

        try:
            from app.run_qa import get_graph
            graph = get_graph()
            results = graph.query("""
                MATCH (c:Car)
                RETURN c.model AS model,
                       c.brand AS brand,
                       c.source_url AS source_url,
                       c.battery_capacity AS battery_capacity,
                       c.range_km AS range_km,
                       c.price_thb AS price_thb,
                       c.weight_kg AS weight_kg,
                       c.fast_charge_kw AS fast_charge_kw,
                       c.horsepower AS horsepower,
                       c.torque_nm AS torque_nm
            """)
            if results:
                self._df_cache = pd.DataFrame(results)
                logger.info(f"[TableAgent] Loaded {len(self._df_cache)} car records into DataFrame.")
            else:
                # Empty dataframe with known columns as fallback
                self._df_cache = pd.DataFrame(columns=[
                    "model", "brand", "battery_capacity", "range_km",
                    "price_thb", "weight_kg", "fast_charge_kw", "horsepower", "torque_nm"
                ])
                logger.warning("[TableAgent] No Car nodes found in graph — DataFrame is empty.")
        except Exception as e:
            logger.error(f"[TableAgent] DataFrame load failed: {e}")
            self._df_cache = pd.DataFrame()

        return self._df_cache

    def run(self, query: str) -> dict:
        """
        Args:
            query: The user's question about specs/comparisons.

        Returns:
            {
                "result": str,    # Markdown table or plain answer
                "context": str,
                "images": list,
                "sources": list,
                "agent": "table"
            }
        """
        df = self._load_dataframe()

        if df.empty:
            # Fallback to text agent if no structured data available
            logger.warning("[TableAgent] No data — falling back to text agent.")
            from app.agents.text_agent import run as text_run
            result = text_run(query)
            result["agent"] = "table_fallback"
            return result

        # Ask LLM to generate Pandas code
        columns_info = ", ".join(df.columns.tolist())
        code_prompt = f"""You have a Pandas DataFrame called `df` with these columns:
{columns_info}

Sample rows:
{df.head(3).to_string()}

Write ONLY Python code (no explanation, no markdown) using `df` to answer this question:
"{query}"

Assign the final answer to a variable called `result`.
`result` must be either a DataFrame, a scalar, or a string.
Do NOT import pandas. Do NOT use print().
"""
        try:
            llm = self._get_llm()
            code_response = llm.invoke(code_prompt).content.strip()
            # Strip markdown code fences if present
            code_response = re.sub(r"^```python\s*|^```\s*|```$", "", code_response, flags=re.MULTILINE).strip()
            logger.info(f"[TableAgent] Generated code:\n{code_response}")

            # Execute safely
            local_vars = {"df": df.copy(), "pd": pd}
            exec(code_response, {"__builtins__": {}}, local_vars)  # noqa: S102
            result = local_vars.get("result")

            # Format result as Markdown
            if isinstance(result, pd.DataFrame):
                markdown_table = result.to_markdown(index=False)
                answer_text = f"### Comparison Results\n\n{markdown_table}"
            elif result is not None:
                answer_text = str(result)
            else:
                answer_text = "No result was returned from the query."

            context = f"[TableAgent] Executed pandas query for: {query}\n{answer_text}"
            return {
                "result": answer_text,
                "context": context,
                "images": [],
                "sources": [],
                "agent": "table"
            }

        except Exception as e:
            logger.error(f"[TableAgent] Code execution failed: {e}")
            # Graceful fallback to text agent
            from app.agents.text_agent import run as text_run
            result = text_run(query)
            result["agent"] = "table_fallback"
            return result


# Module-level singleton
_table_agent = TableAgent()


def run(query: str) -> dict:
    return _table_agent.run(query)

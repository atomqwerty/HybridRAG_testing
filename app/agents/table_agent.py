import os
import pandas as pd
from langchain_openai import ChatOpenAI
from langchain_experimental.agents.agent_toolkits import create_pandas_dataframe_agent
from dotenv import load_dotenv

load_dotenv()

class TableAgent:
    def __init__(self, data_path='data/specs.csv'):
        self.data_path = data_path
        self.agent = None
        self._initialize_agent()
        
    def _initialize_agent(self):
        """Loads CSV and initializes Pandas Agent."""
        try:
            if not os.path.exists(self.data_path):
                print(f"[WARN] Table Data not found at {self.data_path}. Creating dummy.")
                # Create dummy if missing to prevent crash
                df = pd.DataFrame({'Model': ['Mock'], 'Price': [0], 'Battery': [0]})
            else:
                df = pd.read_csv(self.data_path)
                # Cleanup: standardizing column names
                df.columns = [c.strip() for c in df.columns]
                
            llm = ChatOpenAI(
                api_key=os.getenv("OpenAi_api_key"),
                base_url="https://aigateway.ntictsolution.com/v1",
                model="gpt-4o-mini",
                temperature=0.0
            )
            
            self.agent = create_pandas_dataframe_agent(
                llm,
                df,
                verbose=True,
                allow_dangerous_code=True # Required for executing pandas operations
            )
            print("[INFO] Table Agent Initialized.")
            
        except Exception as e:
            print(f"[ERROR] Failed to init Table Agent: {e}")

    def invoke(self, question: str):
        """Answers a question using the dataframe."""
        if not self.agent:
            return "Table Agent is not available."
            
        try:
            response = self.agent.invoke(question)
            return response['output']
        except Exception as e:
            return f"Error querying table: {str(e)}"

# Singleton instance
table_agent = TableAgent()

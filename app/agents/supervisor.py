from typing import Literal
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.pydantic_v1 import BaseModel, Field
try:
    from langchain_core.pydantic_v1 import BaseModel, Field
except ImportError:
    from pydantic import BaseModel, Field

class Route(BaseModel):
    """Route decision structure."""
    intent: Literal["text", "table", "image"] = Field(
        ..., 
        description="The appropriate agent to handle the query."
    )
    reasoning: str = Field(
        ...,
        description="Brief reason for choosing this route."
    )

class Supervisor:
    def __init__(self):
        llm = ChatOpenAI(
            api_key=None, # Will use env var if not set explicitly here, but let's be safe
            base_url="https://aigateway.ntictsolution.com/v1",
            model="gpt-4o-mini",
            temperature=0.0
        )
        # Use structured output for reliable routing
        self.structured_llm = llm.with_structured_output(Route)
        
        self.system_prompt = """You are a Supervisor Router for a car manual RAG system.
        Analyze the user's question and choose the best agent:
        
        1. 'table': Use for SPECIFIC DATA points, COMPARISONS, or technical specs.
           Keywords: price, battery capacity, range, dimension, horsepower, torque, 0-100, compare.
           
        2. 'image': Use for VISUAL requests.
           Keywords: show me, picture of, photo, what does it look like, interior, exterior, color.
           
        3. 'text': Use for GENERAL questions, explanations, warranty, troubleshooting, or "how to".
           Keywords: how to, warranty, manual, troubleshoot, explain.
           
        Default to 'text' if unsure.
        """
        
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", self.system_prompt),
            ("user", "{question}")
        ])
        
        self.chain = self.prompt | self.structured_llm

    def route(self, question: str) -> Route:
        try:
            return self.chain.invoke({"question": question})
        except Exception as e:
            # Fallback to text if router fails
            return Route(intent="text", reasoning=f"Router failed: {str(e)}")

# Singleton
supervisor = Supervisor()

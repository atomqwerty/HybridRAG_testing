import os
from dotenv import load_dotenv
from langchain_community.graphs import Neo4jGraph
from langchain_openai import ChatOpenAI
from langchain.chains import GraphCypherQAChain
from langchain_core.prompts import PromptTemplate

load_dotenv()

# 1. Connect
graph = Neo4jGraph(
    url=os.getenv("NEO4J_URI"),
    username=os.getenv("NEO4J_USERNAME"),
    password=os.getenv("NEO4J_PASSWORD"),
)

graph.refresh_schema()

# 2. LLM
llm = ChatOpenAI(
    api_key=os.getenv("OpenAi_api"),
    base_url="https://aigateway.ntictsolution.com/v1",
    model="gpt-4o",
    temperature=0
)

# 3. Custom Prompt to guide the LLM on your specific schema
CYPHER_GENERATION_PROMPT = PromptTemplate(
    input_variables=["schema", "question"],
    template="""
    You are an expert Neo4j Cypher writer.
    
    My Schema:
    {schema}
    
    My Task:
    1. Find the subject node (e.g. Red Bull).
    2. OPTIONAL: specificy the target type if mentioned (e.g. Engine, Driver).
    3. If asking for 'What X does Y use?', try matching:
       MATCH (y:Entity)-[:USES|RELATED_TO]->(x:Entity)
       WHERE toLower(y.id) CONTAINS toLower("Y") 
       AND (toLower(x.id) CONTAINS toLower("X") OR ANY(label IN labels(x) WHERE toLower(label) CONTAINS toLower("X")))
       RETURN x
    
    IMPORTANT SYNTAX RULES:
    - When using multiple relationship types, do NOT use colons for each one.
    - ✅ CORRECT: [:USES|RELATED_TO|PART_OF]
    - ❌ WRONG: [:USES|:RELATED_TO|:PART_OF]
    
    Question: {question}
    
    Cypher Query:
    """
)

# 4. Chain
chain = GraphCypherQAChain.from_llm(
    llm=llm,
    graph=graph,
    verbose=True,
    validate_cypher=True,
    cypher_prompt=CYPHER_GENERATION_PROMPT
)

# 5. Run
q = "Which engine does Red Bull use?"
print(f"Querying: {q}")
try:
    response = chain.invoke({"query": q})
    print(f"🤖 Answer: {response['result']}")
except Exception as e:
    print(f"Error: {e}")

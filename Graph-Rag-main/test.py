from openai import OpenAI

client = OpenAI(
    api_key="sk-XvTQznrYLhoYfh2km9YG_w",
    base_url="https://aigateway.ntictsolution.com/v1"
)

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[
        {"role": "user", "content": "Hello from normal Python code"}
    ]
)

print(response.choices[0].message.content)

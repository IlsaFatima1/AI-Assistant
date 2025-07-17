from agents import Agent, Runner, AsyncOpenAI, RunConfig, OpenAIChatCompletionsModel
from dotenv import load_dotenv
import os


load_dotenv()
external_client = AsyncOpenAI(
    api_key=os.getenv("GEMINI_API_KEY"),
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
)


external_model= OpenAIChatCompletionsModel(
    model="gemini-2.0-flash",
    openai_client=external_client,
)

Config = RunConfig(
    model = external_model,
    model_provider = external_client,
    tracing_disabled = True,
)
AI= Agent(
    name= "Simple Assistant",
    instructions= "Behave like a simple assistant to help user.",
)

result = Runner.run_sync(
    starting_agent=AI, 
    input="Who is the founder of Pakistan",
    run_config=Config,
)
print(result.final_output)

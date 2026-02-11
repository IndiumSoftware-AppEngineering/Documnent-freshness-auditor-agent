from crewai import Agent, Crew, Process, Task, LLM
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent
from typing import List
import os
from document_freshness_auditor.tools.doc_tools import (
    DocstringSignatureTool, 
    ReadmeStructureTool, 
    ApiImplementationTool, 
    CodeCommentTool,
    ListFilesTool,
    SrsParserTool,
    GitAnalyzerTool,
    DiffGeneratorTool
)
from document_freshness_auditor.tools.freshness_scorer import freshness_scorer

@CrewBase
class DocumentFreshnessAuditor():
    """DocumentFreshnessAuditor crew"""

    agents: List[BaseAgent]
    tasks: List[Task]

    def __init__(self):
        self.llm = LLM(
            model=os.getenv("MODEL_NAME", "llama3.1:8b"),
            base_url=os.getenv("API_BASE")
        )
        self.fix_llm = LLM(
            model=os.getenv("FIX_MODEL_NAME", "gemini-3-flash-preview:cloud"),
            base_url=os.getenv("API_BASE")
        )

    @agent
    def documentation_auditor(self) -> Agent:
        return Agent(
            config=self.agents_config['documentation_auditor'],
            tools=[
                DocstringSignatureTool(), 
                ReadmeStructureTool(), 
                ApiImplementationTool(), 
                CodeCommentTool(),
                ListFilesTool(),
                SrsParserTool(),
                GitAnalyzerTool()
            ],
            llm=self.llm,
            verbose=True
        )

    @agent
    def freshness_scorer(self) -> Agent:
        return Agent(
            config=self.agents_config['freshness_scorer'],
            llm=self.llm,
            verbose=True,
            tools=[freshness_scorer]
        )

    @agent
    def fix_suggester(self) -> Agent:
        return Agent(
            config=self.agents_config['fix_suggester'],
            llm=self.fix_llm,
            verbose=True,
            tools=[DiffGeneratorTool()]
        )

    @task
    def audit_task(self) -> Task:
        return Task(
            config=self.tasks_config['audit_task'],
        )

    @task
    def freshness_scorer_task(self) -> Task:
        return Task(
            config=self.tasks_config['freshness_scorer_task'],
        )

    @task
    def suggestion_task(self) -> Task:
        return Task(
            config=self.tasks_config['suggestion_task'],
            output_file='freshness_audit_report.md'
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )

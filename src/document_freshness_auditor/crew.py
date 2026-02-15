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
    DiffGeneratorTool,
    ReadFileTool
)
from document_freshness_auditor.tools.freshness_scorer import freshness_scorer


@CrewBase
class DocumentFreshnessAuditor():

    agents: List[BaseAgent]
    tasks: List[Task]



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
            verbose=True
        )

    @agent
    def freshness_scorer(self) -> Agent:
        return Agent(
            config=self.agents_config['freshness_scorer'],
            verbose=True,
            tools=[freshness_scorer]
        )

    @agent
    def fix_suggester(self) -> Agent:
        return Agent(
            config=self.agents_config['fix_suggester'],
            verbose=True,
            tools=[ReadFileTool(), DiffGeneratorTool()]
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

    def analysis_only_crew(self) -> Crew:
        return Crew(
            agents=[self.documentation_auditor(), self.freshness_scorer()],
            tasks=[self.audit_task(), self.freshness_scorer_task()],
            process=Process.sequential,
            verbose=True,
        )

    def fix_only_crew(self) -> Crew:
        suggestion = Task(
            config=self.tasks_config['suggestion_task'],
            human_input=False,
            output_file='freshness_audit_report.md'
        )
        return Crew(
            agents=[self.fix_suggester()],
            tasks=[suggestion],
            process=Process.sequential,
            verbose=True,
        )

    def hitl_crew(self) -> Crew:
        suggestion = Task(
            config=self.tasks_config['suggestion_task'],
            human_input=True,
            output_file='freshness_audit_report.md'
        )
        return Crew(
            agents=[self.documentation_auditor(), self.freshness_scorer(), self.fix_suggester()],
            tasks=[self.audit_task(), self.freshness_scorer_task(), suggestion],
            process=Process.sequential,
            verbose=True,
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
            human_input=False
        )

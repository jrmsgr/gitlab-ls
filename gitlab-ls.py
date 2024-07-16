#!/usr/bin/env python3

import asyncio
import dataclasses
from pathlib import Path
from dataclasses import dataclass
from dataclasses_json import dataclass_json
import logging
import gitlab
from typing import List, Dict, Any
from gitlab.v4.objects import Project, projects
from pygls.server import LanguageServer
from lsprotocol import types
import json
import datetime
import os


@dataclass_json
@dataclass
class GitlabIssue:
    id: int
    title: str
    author: str
    open: bool

    def to_completion_item(self):
        return types.CompletionItem(
            label=f"#{self.id} {self.title}",
            kind=(types.CompletionItemKind.Method if self.open else types.CompletionItemKind.Text),
        )


@dataclass_json
@dataclass
class GitlabMergeRequest:
    id: int
    title: str
    author: str
    open: bool

    def to_completion_item(self):
        return types.CompletionItem(
            label=f"!{self.id} {self.title}",
            kind=(types.CompletionItemKind.Method if self.open else types.CompletionItemKind.Text),
        )


@dataclass_json
@dataclass
class GitlabProject:
    id: int
    path: str
    last_update: str
    issues: List[GitlabIssue]
    merge_requests: List[GitlabMergeRequest]


class EnhancedJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if dataclasses.is_dataclass(o):
            return o.to_json()
        return super().default(o)


@dataclass
class WorkProgress:
    token: int
    increment: int
    progress: int = 0

    def advance(self):
        self.progress += self.increment


class GitlabManager:
    def __init__(self, gl: gitlab.Gitlab, ls: LanguageServer) -> None:
        self.client = gl
        self.ls = ls
        self.projects: Dict[str, GitlabProject] = {}
        self.log_path = Path(os.environ["HOME"]) / ".local/share/gitlab-ls/state.json"

    def load_projects(self, projects: List[str]):
        progress = WorkProgress(token=1, increment=int(100 / len(projects)))
        self.ls.progress.create(progress.token)
        self.ls.progress.begin(
            progress.token,
            types.WorkDoneProgressBegin(title="Database load", message="Starting progress", percentage=0),
        )
        cache = self.load_state()
        for project_name in cache:
            logging.debug(f"project in cache: {project_name}")
            idx = next((i for i in range(len(projects)) if projects[i] == project_name), None)
            if idx is None:
                continue
            logging.debug(f"Found project in cache: {project_name}")
            logging.debug(f"cache: {cache[project_name]}")
            project = GitlabProject.from_dict(cache[project_name])
            self.projects[project.path] = project
            self.report_progress(progress, f"Updating {project.path}")
            self.update_project(project.path)
            projects.pop(idx)
            progress.advance()
            self.report_progress(progress, f"Updated {project.path}")
        if len(projects) > 0:
            self.fetch_projects(projects, progress)
        self.save_state()
        self.ls.progress.end(progress.token, types.WorkDoneProgressEnd(message=f"Database loaded!"))

    def update_project(self, project_name: str) -> None:
        project = self.projects[project_name]
        project.issues += self.get_issue_list(
            project=self.client.projects.get(project.id),
            created_after=project.last_update,
        )
        project.merge_requests += self.get_merge_request_list(
            project=self.client.projects.get(project.id),
            created_after=project.last_update,
        )
        project.last_update = self.get_timestamp()
        self.projects[project_name] = project

    @staticmethod
    def get_timestamp() -> str:
        return datetime.datetime.now().replace(microsecond=0).isoformat()

    def fetch_projects(self, project_paths: List, progress: WorkProgress) -> None:
        self.report_progress(progress, "Fetching missing projects")
        for fetched_project in self.client.projects.list(get_all=True):
            if fetched_project.path_with_namespace in project_paths:
                logging.debug(f"Found project: {fetched_project.path_with_namespace}")
                self.report_progress(
                    progress,
                    f"Fetching missing project: {fetched_project.path_with_namespace}",
                )
                issue_list = self.get_issue_list(fetched_project)
                merge_request_list = self.get_merge_request_list(fetched_project)
                project = GitlabProject(
                    id=fetched_project.id,
                    path=fetched_project.path_with_namespace,
                    issues=issue_list,
                    merge_requests=merge_request_list,
                    last_update=self.get_timestamp(),
                )
                self.projects[project.path] = project
                progress.advance()
                self.report_progress(progress, f"Fetched project {project.path}")

    def save_state(self):
        if not self.log_path.exists():
            os.makedirs(self.log_path.parent, exist_ok=True)
        with open(self.log_path, "w+") as fp:
            projects = {}
            for name, project in self.projects.items():
                projects[name] = project.to_dict()
            json.dump(projects, fp, indent=2)

    def load_state(self) -> Dict[Any, Any]:
        if not self.log_path.exists():
            return {}
        with open(self.log_path, "r") as fp:
            logging.debug("Loading state.json")
            return json.load(fp)

    def report_progress(self, progress: WorkProgress, msg: str):
        self.ls.progress.report(
            progress.token,
            types.WorkDoneProgressReport(message=msg, percentage=progress.progress),
        )

    @staticmethod
    def get_issue_list(project: Project, created_after: str = None) -> List[GitlabIssue]:
        issue_list = []

        logging.debug(f"Getting issue list for project: {project.path_with_namespace} from date: {created_after}")
        if created_after is None:
            issues = project.issues.list(get_all=True)
        else:
            issues = project.issues.list(created_after=created_after)

        for issue in issues:
            issue_list.append(
                GitlabIssue(
                    id=issue.iid,
                    title=issue.title,
                    author=issue.author["name"],
                    open=(issue.state == "opened"),
                )
            )
        logging.debug(f"Got {len(issue_list)} results")
        return issue_list

    @staticmethod
    def get_merge_request_list(project: Project, created_after: str = None) -> List[GitlabMergeRequest]:
        merge_request_list = []
        logging.debug(
            f"Getting merge request list for project: {project.path_with_namespace} from date: {created_after}"
        )
        if created_after is None:
            merge_requests = project.mergerequests.list(get_all=True)
        else:
            merge_requests = project.mergerequests.list(created_after=created_after)
        for mr in merge_requests:
            merge_request_list.append(
                GitlabIssue(
                    id=mr.iid,
                    title=mr.title,
                    author=mr.author["name"],
                    open=(mr.state == "opened"),
                )
            )
        logging.debug(f"Got {len(merge_request_list)} results")
        return merge_request_list


log_file = Path("/tmp/") / os.environ["USER"] / "gitlab-ls.log"
os.makedirs(log_file.parent, exist_ok=True)
logging.basicConfig(filename=log_file, filemode="w", level=logging.DEBUG)
server = LanguageServer("gitlab-ls", "v0.1")
gl = gitlab.Gitlab.from_config("axelera", ["./config.cfg"])
manager = GitlabManager(gl, server)


@server.feature(types.INITIALIZE)
async def fetch_database(params: types.InitializeParams):
    manager.load_projects(params.initialization_options["projects"])


@server.feature(
    types.TEXT_DOCUMENT_COMPLETION,
    types.CompletionOptions(trigger_characters=["!", "#", "@"]),
)
def completions(params: types.CompletionParams):
    items = []
    match params.context.trigger_character:
        case "!":
            for project in manager.projects.values():
                for merge_request in project.merge_requests:
                    item = merge_request.to_completion_item()
                    item.label_details = types.CompletionItemLabelDetails(detail=project.path)
                    items.append(item)
        case "#":
            for project in manager.projects.values():
                for issue in project.issues:
                    item = issue.to_completion_item()
                    item.label_details = types.CompletionItemLabelDetails(detail=project.path)
                    items.append(item)
        case _:
            return []
    return items


if __name__ == "__main__":
    server.start_io()

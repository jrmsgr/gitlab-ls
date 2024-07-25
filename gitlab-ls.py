#!/usr/bin/env python3

import asyncio
import dataclasses
from pathlib import Path
from dataclasses import dataclass
from dataclasses_json import dataclass_json
import logging
import gitlab
from typing import List, Dict, Any, Optional
from gitlab.v4.objects import Project
from pygls.server import LanguageServer
from lsprotocol import types
import json
import datetime
import os
import re


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
    issues: Dict[int, GitlabIssue]
    merge_requests: Dict[int, GitlabMergeRequest]


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


class GitlabLanguageServer(LanguageServer):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.client = None
        self.projects: Dict[str, GitlabProject] = {}
        self.index_path = Path(os.environ["HOME"]) / ".local/share/gitlab-ls/index.json"

    def init_gitlab(self, client: gitlab.Gitlab):
        self.client = client

    def load_projects(self, projects: List[str]):
        progress = WorkProgress(token=1, increment=int(100 / len(projects)))
        self.progress.create(progress.token)
        self.progress.begin(
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
        self.progress.end(progress.token, types.WorkDoneProgressEnd(message=f"Database loaded!"))

    def update_project(self, project_name: str) -> None:
        project = self.projects[project_name]
        project.issues |= self.get_issue_dict(
            project=self.client.projects.get(project.id),
            updated_after=project.last_update,
        )
        project.merge_requests |= self.get_merge_request_dict(
            project=self.client.projects.get(project.id),
            updated_after=project.last_update,
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
                issue_dict = self.get_issue_dict(fetched_project)
                merge_request_dict = self.get_merge_request_dict(fetched_project)
                project = GitlabProject(
                    id=fetched_project.id,
                    path=fetched_project.path_with_namespace,
                    issues=issue_dict,
                    merge_requests=merge_request_dict,
                    last_update=self.get_timestamp(),
                )
                self.projects[project.path] = project
                progress.advance()
                self.report_progress(progress, f"Fetched project {project.path}")

    def save_state(self):
        if not self.index_path.exists():
            os.makedirs(self.index_path.parent, exist_ok=True)
        with open(self.index_path, "w+") as fp:
            projects = {}
            for name, project in self.projects.items():
                projects[name] = project.to_dict()
            json.dump(projects, fp, indent=2)

    def load_state(self) -> Dict[Any, Any]:
        if not self.index_path.exists():
            return {}
        with open(self.index_path, "r") as fp:
            logging.debug(f"Loading {self.index_path}")
            return json.load(fp)

    def report_progress(self, progress: WorkProgress, msg: str):
        self.progress.report(
            progress.token,
            types.WorkDoneProgressReport(message=msg, percentage=progress.progress),
        )

    @staticmethod
    def get_issue_dict(project: Project, updated_after: str = None) -> Dict[int, GitlabIssue]:
        issue_dict = {}

        logging.debug(f"Getting issue list for project: {project.path_with_namespace} from date: {updated_after}")
        if updated_after is None:
            issues = project.issues.list(iterator=True, get_all=True)
        else:
            issues = project.issues.list(iterator=True, updated_after=updated_after)

        for issue in issues:
            issue_dict[issue.iid] = GitlabIssue(
                id=issue.iid,
                title=issue.title,
                author=issue.author["name"],
                open=(issue.state == "opened"),
            )
        logging.debug(f"Got {len(issue_dict.keys())} results")
        return issue_dict

    @staticmethod
    def get_merge_request_dict(project: Project, updated_after: str = None) -> Dict[int, GitlabMergeRequest]:
        merge_request_dict = {}
        logging.debug(
            f"Getting merge request list for project: {project.path_with_namespace} from date: {updated_after}"
        )
        if updated_after is None:
            merge_requests = project.mergerequests.list(iterator=True, get_all=True)
        else:
            merge_requests = project.mergerequests.list(iterator= True, updated_after=updated_after)
            logging.debug(f"Updated after={updated_after}")
        for mr in merge_requests:
            logging.debug(f"Got mr: {mr.iid}-{mr.title}-{mr.state}")
            merge_request_dict[mr.iid] = GitlabIssue(
                id=mr.iid,
                title=mr.title,
                author=mr.author["name"],
                open=(mr.state == "opened"),
            )
            if mr.iid ==886:
                logging.debug(f"{mr}")
                logging.debug(f"{merge_request_dict[mr.iid]}")
        logging.debug(f"Got {len(merge_request_dict.keys())} results")
        return merge_request_dict


log_file = Path("/tmp/") / os.environ["USER"] / "gitlab-ls.log"
os.makedirs(log_file.parent, exist_ok=True)
logging.basicConfig(filename=log_file, filemode="w", level=logging.DEBUG)
server = GitlabLanguageServer("gitlab-ls", "v0.1")


@server.feature(types.INITIALIZE)
async def fetch_database(ls: GitlabLanguageServer, params: types.InitializeParams):
    init_options = params.initialization_options
    client = gitlab.Gitlab(url=init_options["url"], private_token=init_options["private_token"])
    ls.init_gitlab(client)
    ls.load_projects(init_options["projects"])


@server.feature(
    types.TEXT_DOCUMENT_COMPLETION,
    types.CompletionOptions(trigger_characters=["!", "#"]),
)
def completions(ls: GitlabLanguageServer, params: types.CompletionParams):
    items = []
    match params.context.trigger_character:
        case "!":
            for project in ls.projects.values():
                for merge_request in project.merge_requests.values():
                    item = merge_request.to_completion_item()
                    item.label_details = types.CompletionItemLabelDetails(detail=project.path)
                    items.append(item)
        case "#":
            for project in ls.projects.values():
                for issue in project.issues.values():
                    item = issue.to_completion_item()
                    item.label_details = types.CompletionItemLabelDetails(detail=project.path)
                    items.append(item)
        case _:
            return []
    return items


@server.feature(
    types.TEXT_DOCUMENT_DIAGNOSTIC,
    types.DiagnosticOptions(
        identifier=server.name,
        inter_file_dependencies=False,
        workspace_diagnostics=False,
    ),
)
def diagnostics(ls: GitlabLanguageServer, params: types.DocumentDiagnosticParams):
    gitlab_url_regex = re.compile(r"\b" + f"{ls.client.url}" + r"/([^ ]+)/-/(issues|merge_requests)/(\d+)\b")
    doc = ls.workspace.get_text_document(params.text_document.uri)
    diagnostics = []
    for line_nr, line in enumerate(doc.lines):
        for m in gitlab_url_regex.finditer(line):
            # logging.debug("Found link")
            project_path = m.group(1)
            if project_path not in ls.projects:
                continue
            project = ls.projects[project_path]
            is_issue = m.group(2) == "issues"
            iid = int(m.group(3))
            if is_issue:
                if iid not in project.issues:
                    continue
                is_open = project.issues[iid].open
            else:
                if iid not in project.merge_requests:
                    continue
                is_open = project.merge_requests[iid].open

            message = "open" if is_open else "closed"
            severity = types.DiagnosticSeverity.Information if is_open else types.DiagnosticSeverity.Error

            start = types.Position(line=line_nr, character=m.start())
            end = types.Position(line=line_nr, character=m.end())
            diagnostics.append(
                types.Diagnostic(
                    range=types.Range(start=start, end=end),
                    message=message,
                    severity=severity,
                )
            )
            # logging.debug(f"{project_name}: {is_issue}, {iid}")

    return types.RelatedFullDocumentDiagnosticReport(items=diagnostics)


if __name__ == "__main__":
    server.start_io()

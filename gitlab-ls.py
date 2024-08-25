#!/usr/bin/env python3

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
class GitlabObject:
    id: int
    title: str
    author: str
    state: str
    description: str

    def to_completion_item(self, is_issue=False):
        return types.CompletionItem(
            label=f"{'#' if is_issue else '!'}{self.id} {self.title}",
            kind=(types.CompletionItemKind.Method if self.state == "opened" else types.CompletionItemKind.Text),
        )


@dataclass_json
@dataclass
class GitlabProject:
    id: int
    path: str
    last_update: str
    issues: Dict[int, GitlabObject]
    merge_requests: Dict[int, GitlabObject]


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
        self.gitlab_url_regex = re.compile(r"\b" + f"{self.client.url}" + r"/([^ ]+)/-/(issues|merge_requests)/(\d+)\b")

    def get_gitlab_object_from_url_match(self, m: re.Match[str] | None) -> Optional[GitlabObject]:
        if m is None:
            return None
        project_path = m.group(1)
        if project_path not in self.projects:
            return None
        project = self.projects[project_path]
        is_issue = m.group(2) == "issues"
        iid = int(m.group(3))
        gitlab_objects = project.issues if is_issue else project.merge_requests
        if iid not in gitlab_objects:
            return None
        return gitlab_objects[iid]

    def get_gitlab_objects_from_line(self, line: str) -> list[tuple[GitlabObject, int, int]]:
        gitlab_objects = []
        for m in self.gitlab_url_regex.finditer(line):
            gitlab_object = self.get_gitlab_object_from_url_match(m)
            if gitlab_object is not None:
                gitlab_objects.append((gitlab_object, m.start(), m.end()))
        return gitlab_objects

    def get_gitlab_object_from_url(self, url: str) -> Optional[GitlabObject]:
        m = self.gitlab_url_regex.match(url)
        return self.get_gitlab_object_from_url_match(m)

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
        if self.client is None:
            return
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
        if self.client is None:
            return
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
    def get_issue_dict(project: Project, updated_after: Optional[str] = None) -> Dict[int, GitlabObject]:
        issue_dict = {}

        logging.debug(f"Getting issue list for project: {project.path_with_namespace} from date: {updated_after}")
        if updated_after is None:
            issues = project.issues.list(iterator=True, get_all=True)
        else:
            issues = project.issues.list(iterator=True, updated_after=updated_after)

        for issue in issues:
            issue_dict[issue.iid] = GitlabObject(
                id=issue.iid,
                title=issue.title,
                author=issue.author["name"],
                state=issue.state,
                description=issue.description,
            )
        logging.debug(f"Got {len(issue_dict.keys())} results")
        return issue_dict

    @staticmethod
    def get_merge_request_dict(project: Project, updated_after: Optional[str] = None) -> Dict[int, GitlabObject]:
        merge_request_dict = {}
        logging.debug(
            f"Getting merge request list for project: {project.path_with_namespace} from date: {updated_after}"
        )
        if updated_after is None:
            merge_requests = project.mergerequests.list(iterator=True, get_all=True)
        else:
            merge_requests = project.mergerequests.list(iterator=True, updated_after=updated_after)
            logging.debug(f"Updated after={updated_after}")
        for mr in merge_requests:
            logging.debug(f"Got mr: {mr.iid}-{mr.title}-{mr.state}")
            merge_request_dict[mr.iid] = GitlabObject(
                id=mr.iid,
                title=mr.title,
                author=mr.author["name"],
                state=mr.state,
                description=mr.description,
            )
        logging.debug(f"Got {len(merge_request_dict.keys())} results")
        return merge_request_dict


log_file = Path("/tmp/") / os.environ["USER"] / "gitlab-ls.log"
os.makedirs(log_file.parent, exist_ok=True)
logging.basicConfig(filename=log_file, filemode="w", level=logging.DEBUG)
server = GitlabLanguageServer("gitlab-ls", "v0.1")


@server.feature(types.INITIALIZE)
async def fetch_database(ls: GitlabLanguageServer, params: types.InitializeParams):
    init_options = params.initialization_options
    if init_options is None:
        ls.show_message("init_options is invalid", types.MessageType.Error)
        exit(1)
    client = gitlab.Gitlab(url=init_options["url"], private_token=init_options["private_token"])
    ls.init_gitlab(client)
    ls.load_projects(init_options["projects"])


@server.feature(
    types.TEXT_DOCUMENT_COMPLETION,
    types.CompletionOptions(trigger_characters=["!", "#"]),
)
def completions(ls: GitlabLanguageServer, params: types.CompletionParams):
    items = []
    if params.context is None:
        return
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
                    item = issue.to_completion_item(is_issue=True)
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
    doc = ls.workspace.get_text_document(params.text_document.uri)
    diagnostics = []
    for line_nr, line in enumerate(doc.lines):
        gitlab_objects_and_pos = ls.get_gitlab_objects_from_line(line)
        for gitlab_object, pos_start, pos_end in gitlab_objects_and_pos:
            message = gitlab_object.state
            if gitlab_object.state == "opened":
                severity = types.DiagnosticSeverity.Hint
            elif gitlab_object.state == "merged":
                severity = types.DiagnosticSeverity.Information
            else:
                severity = types.DiagnosticSeverity.Error
            start = types.Position(line=line_nr, character=pos_start)
            end = types.Position(line=line_nr, character=pos_end)
            diagnostics.append(
                types.Diagnostic(
                    range=types.Range(start=start, end=end),
                    message=message,
                    severity=severity,
                )
            )

    return types.RelatedFullDocumentDiagnosticReport(items=diagnostics)


URL_RE_END_WORD = re.compile(r"^\S*")
URL_RE_START_WORD = re.compile(r"\S*$")


@server.feature(types.TEXT_DOCUMENT_HOVER)
def hover(ls: GitlabLanguageServer, params: types.HoverParams):
    pos = params.position
    document_uri = params.text_document.uri
    document = ls.workspace.get_text_document(document_uri)

    url = document.word_at_position(pos, URL_RE_START_WORD, URL_RE_END_WORD)
    gitlab_object = ls.get_gitlab_object_from_url(url)
    if gitlab_object is None:
        return

    return types.Hover(
        contents=types.MarkupContent(
            kind=types.MarkupKind.Markdown,
            value=f"{gitlab_object.title}\n-----\n{gitlab_object.description}",
        ),
        range=types.Range(
            start=types.Position(line=pos.line, character=0),
            end=types.Position(line=pos.line + 1, character=0),
        ),
    )


if __name__ == "__main__":
    server.start_io()

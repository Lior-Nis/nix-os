#!/usr/bin/env python3
"""Preview or apply canonical profile skill packs through pinned NixKit."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_MANIFEST = ROOT / "skills/packs.json"
PROFILE_MAP = {"lnx":"default","pulse":"pulse","algua":"algua","meabeclick":"meabeclick","meabeclickux":"meabeclickux","meabeclickeng":"meabeclickeng","meabeclickgrowth":"meabeclickgrowth"}
PROFILES = set(PROFILE_MAP)
NIXKIT_REPOSITORY = "https://github.com/its-nix/kit.git"
NIXKIT_COMMIT = "5d9ac621d4b2862c94ff8aa419f2f9fc6c9f68f4"
NIXKIT_SOURCES_SHA256 = "8c465cac697c5dc90a37e3a75242bac2f178c8768d7181883a3b9d673670b656"
NODE_RUNTIME = "24.22.1"
EXPECTED_PACKS = {
 "baseline-evidence":["verification-before-completion"],
 "orchestrator-control":["dispatching-parallel-agents","receiving-code-review","handoff"],
 "project-lead-core":["brainstorming","domain-modeling","to-spec","to-tickets","codebase-design","receiving-code-review","handoff"],
 "public-research":[],
 "engineering-delivery":["executing-plans","using-git-worktrees","finishing-a-development-branch","receiving-code-review","codebase-design"],
 "ux-design-review":["frontend-design"],
}
EXPECTED_ASSIGNMENTS = {
 "lnx":["baseline-evidence","orchestrator-control"], "pulse":["baseline-evidence","project-lead-core","public-research"],
 "algua":["baseline-evidence","project-lead-core","public-research"], "meabeclick":["baseline-evidence","project-lead-core","public-research"],
 "meabeclickux":["baseline-evidence","ux-design-review"], "meabeclickeng":["baseline-evidence","engineering-delivery"],
 "meabeclickgrowth":["baseline-evidence","public-research"],
}
NIXKIT_SKILLS = {"using-superpowers","brainstorming","writing-plans","executing-plans","systematic-debugging","test-driven-development","verification-before-completion","requesting-code-review","receiving-code-review","using-git-worktrees","finishing-a-development-branch","subagent-driven-development","dispatching-parallel-agents","diagnosing-superpowers","setup-matt-pocock-skills","grill-with-docs","grilling","domain-modeling","to-spec","to-tickets","codebase-design","research","handoff","caveman","ponytail","frontend-design","web-design-guidelines","agent-browser","remotion-best-practices","auto-editor","auto-editor-effects","auto-editor-export","auto-editor-transcribe","obsidian-markdown","qmd","gws-shared","gws-drive","gws-docs","gws-drive-upload","gws-docs-write","find-docs"}
HARD_GATES = {"relevance","provenance","reliability","safety_privacy","license","hermes_compatibility","non_duplication"}
SCORE_LIMITS = {"role_value":30,"evidence_quality":20,"security_provenance":20,"hermes_compatibility":15,"maintenance":10,"documentation_license":5}
SHA = re.compile(r"^[a-f0-9]{40}$")
SKILL = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PROPOSAL_ID = re.compile(r"^[a-z0-9][a-z0-9.-]+$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SKILL_PATH = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*$")
RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
MAX_TEXT = 4_096
MAX_URL = 2_048
MAX_EVIDENCE_URLS = 100
MAX_RISKS = 50

class Refusal(RuntimeError): pass

def _run(command:list[str], cwd:Path)->str:
 result=subprocess.run(command,cwd=cwd,text=True,capture_output=True,check=False)
 if result.returncode:
  raise Refusal(f"command failed: {' '.join(command)}: {result.stderr.strip() or result.stdout.strip() or result.returncode}")
 return result.stdout.strip()

def _load_json(path:Path,label:str)->dict:
 try: value=json.loads(path.read_text(encoding="utf-8"))
 except (OSError,UnicodeError,json.JSONDecodeError) as exc: raise Refusal(f"cannot read {label}: {exc}") from exc
 if not isinstance(value,dict): raise Refusal(f"{label} root must be an object")
 return value

def _source_catalog(path:Path)->dict[str,tuple[str,str]]:
 try: value=json.loads(path.read_text(encoding="utf-8"))
 except (OSError,UnicodeError,json.JSONDecodeError) as exc: raise Refusal(f"cannot parse pinned NixKit sources.json: {exc}") from exc
 if not isinstance(value,list): raise Refusal("pinned NixKit sources.json root must be an array")
 catalog:dict[str,tuple[str,str]]={}
 for source in value:
  if not isinstance(source,dict) or set(source)!={"repo","ref","skills"} or not isinstance(source.get("repo"),str) or not REPOSITORY.fullmatch(source["repo"]) or not isinstance(source.get("ref"),str) or not SHA.fullmatch(source["ref"]) or not isinstance(source.get("skills"),list): raise Refusal("pinned NixKit sources.json has an invalid source record")
  for skill in source["skills"]:
   if not isinstance(skill,str) or not SKILL.fullmatch(skill) or skill in catalog: raise Refusal("pinned NixKit sources.json skill names must be valid and globally unique")
   catalog[skill]=(source["repo"],source["ref"])
 if set(catalog)!=NIXKIT_SKILLS: raise Refusal("pinned NixKit sources.json does not contain the exact audited skill catalog")
 return catalog

def _canonical_manifest(manifest:dict)->None:
 if set(manifest)!={"schema_version","nixkit","packs","profiles","approved_additions","task_only","excluded","governance"} or manifest.get("schema_version")!=1: raise Refusal("canonical pack manifest has invalid fields")
 if manifest.get("nixkit")!={"repository":NIXKIT_REPOSITORY,"commit":NIXKIT_COMMIT,"sources_sha256":NIXKIT_SOURCES_SHA256,"node_runtime":NODE_RUNTIME}: raise Refusal("canonical manifest does not match compile-time NixKit pins")
 if manifest.get("packs")!=EXPECTED_PACKS or manifest.get("profiles")!=EXPECTED_ASSIGNMENTS: raise Refusal("canonical manifest does not match the exact seven-profile pack topology")
 additions=manifest.get("approved_additions")
 if not isinstance(additions,dict) or set(additions)!=set(PROFILE_MAP) or any(not isinstance(v,list) or len(v)!=len(set(v)) or any(not isinstance(x,str) or not SKILL.fullmatch(x) for x in v) for v in additions.values()): raise Refusal("canonical manifest has invalid approved additions topology")
 persistent=set().union(*(set(v) for v in EXPECTED_PACKS.values())); task=manifest.get("task_only"); excluded=manifest.get("excluded")
 if not isinstance(task,list) or not isinstance(excluded,list) or len(task)!=len(set(task)) or len(excluded)!=len(set(excluded)) or persistent & set(task) or persistent & set(excluded) or set(task)&set(excluded) or persistent|set(task)|set(excluded)!=NIXKIT_SKILLS: raise Refusal("canonical manifest does not classify the exact NixKit catalog")
 governance=manifest.get("governance")
 if not isinstance(governance,dict) or set(governance.get("hard_gates",[]))!=HARD_GATES or governance.get("minimum_score")!=80 or governance.get("approval_authority")!="Lior": raise Refusal("canonical manifest governance is invalid")

def _tracked_clean(relative:Path)->None:
 _run(["git","ls-files","--error-unmatch",relative.as_posix()],ROOT)
 if _run(["git","status","--porcelain=v1","--untracked-files=all","--",relative.as_posix()],ROOT): raise Refusal(f"canonical governance file is dirty: {relative.as_posix()}")

def _git_json(commit:str,relative:Path,label:str)->dict:
 try: raw=_run(["git","show",f"{commit}:{relative.as_posix()}"],ROOT); value=json.loads(raw)
 except (Refusal,json.JSONDecodeError) as exc: raise Refusal(f"cannot load committed {label} at {commit}: {exc}") from exc
 if not isinstance(value,dict): raise Refusal(f"committed {label} must be an object")
 return value

def _valid_datetime(value:object)->bool:
 if not isinstance(value,str) or not RFC3339.fullmatch(value): return False
 try: parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
 except ValueError: return False
 return parsed.tzinfo is not None and parsed.utcoffset() is not None

def _validate_proposal(p:dict,proposal_id:str,profile:str,skills:set[str],catalog:dict[str,tuple[str,str]])->None:
 required={"schema_version","proposal_id","profile","name","summary","rationale","source_url","repository","skill_path","revision","license","evidence_urls","risks","score_components","score","gates","gate_evidence","status"}
 if set(p)!=required or p.get("schema_version")!=1 or not isinstance(p.get("proposal_id"),str) or not PROPOSAL_ID.fullmatch(p["proposal_id"]) or p.get("proposal_id")!=proposal_id or p.get("profile") not in PROFILES or p.get("profile")!=profile or p.get("status")!="candidate" or not isinstance(p.get("name"),str) or not SKILL.fullmatch(p["name"]) or {p["name"]}!=skills: raise Refusal("committed proposal identity/status/skills do not match approval")
 if not isinstance(p.get("repository"),str) or not REPOSITORY.fullmatch(p["repository"]) or not isinstance(p.get("skill_path"),str) or not SKILL_PATH.fullmatch(p["skill_path"]) or not SHA.fullmatch(str(p.get("revision",""))): raise Refusal("committed proposal repository/path/revision is invalid")
 if catalog.get(p["name"])!=(p["repository"],p["revision"]): raise Refusal("approved skill does not uniquely belong to the proposal repository and pinned revision")
 source=f"https://github.com/{p['repository']}/tree/{p['revision']}/{p.get('skill_path','')}"
 if not isinstance(p.get("source_url"),str) or len(p["source_url"])>MAX_URL or p["source_url"]!=source: raise Refusal("committed proposal source evidence is not immutable and exact")
 license_prefixes=(f"/{p['repository']}/blob/{p['revision']}/",f"/{p['repository']}/tree/{p['revision']}/")
 def license_url(u:object)->bool:
  if not isinstance(u,str): return False
  parsed=urlsplit(u)
  if parsed.scheme!="https" or parsed.netloc!="github.com" or parsed.username is not None or parsed.password is not None or parsed.port is not None or parsed.query or parsed.fragment: return False
  if not any(parsed.path.startswith(prefix) for prefix in license_prefixes): return False
  relative=next(parsed.path[len(prefix):] for prefix in license_prefixes if parsed.path.startswith(prefix))
  return any(re.fullmatch(r"(?:LICENSE|COPYING|NOTICE)(?:[._-].*)?",part,re.I) for part in relative.split("/") if part)
 evidence=p.get("evidence_urls")
 if not isinstance(evidence,list) or not 2<=len(evidence)<=MAX_EVIDENCE_URLS or any(not isinstance(u,str) or not u.strip() or len(u)>MAX_URL or urlsplit(u).scheme!="https" or not urlsplit(u).netloc or urlsplit(u).username is not None or urlsplit(u).password is not None for u in evidence) or source not in evidence or not any(license_url(u) for u in evidence): raise Refusal("committed proposal lacks immutable same-origin source/license evidence")
 risks=p.get("risks")
 if not isinstance(risks,list) or len(risks)>MAX_RISKS or any(not isinstance(risk,str) or not risk.strip() or len(risk)>MAX_TEXT for risk in risks): raise Refusal("committed proposal risks are invalid")
 components=p.get("score_components"); score=p.get("score")
 if not isinstance(components,dict) or set(components)!=set(SCORE_LIMITS) or any(isinstance(components[k],bool) or not isinstance(components[k],int) or not 0<=components[k]<=SCORE_LIMITS[k] for k in SCORE_LIMITS) or isinstance(score,bool) or not isinstance(score,int) or not 80<=score<=100 or score!=sum(components.values()): raise Refusal("committed proposal score is invalid")
 if p.get("gates")!={k:True for k in HARD_GATES} or not isinstance(p.get("gate_evidence"),dict) or set(p["gate_evidence"])!=HARD_GATES or any(not isinstance(v,str) or not v.strip() or len(v)>MAX_TEXT for v in p["gate_evidence"].values()): raise Refusal("committed proposal gates/evidence are invalid")
 for field in ("summary","rationale","license"):
  if not isinstance(p.get(field),str) or not p[field].strip() or len(p[field])>MAX_TEXT: raise Refusal(f"committed proposal {field} is invalid")

def _approval(path:Path,profile:str,current:dict,requested:set[str],catalog:dict[str,tuple[str,str]])->None:
 for governance_file in (Path("skills/packs.json"), Path("scripts/install-skills.py")): _tracked_clean(governance_file)
 try: relative=path.resolve(strict=True).relative_to(ROOT.resolve())
 except (OSError,ValueError) as exc: raise Refusal("approval receipt must be a canonical path inside this repository") from exc
 _tracked_clean(relative)
 approval=_load_json(path,"approval receipt"); required={"schema_version","proposal_id","profile","skills","approved_by","approved_at","manifest_commit"}
 if set(approval)!=required or approval.get("schema_version")!=1 or approval.get("profile")!=profile or approval.get("approved_by")!="Lior": raise Refusal("malformed or misbound approval receipt")
 proposal_id=approval.get("proposal_id")
 if not isinstance(proposal_id,str) or not PROPOSAL_ID.fullmatch(proposal_id) or relative!=Path("skills/approvals")/f"{proposal_id}.json": raise Refusal("approval receipt is not at its canonical proposal-bound path")
 skills=approval.get("skills"); commit=approval.get("manifest_commit")
 if not isinstance(skills,list) or set(skills)!=requested or len(skills)!=len(set(skills)) or not skills or any(not isinstance(x,str) or not SKILL.fullmatch(x) for x in skills): raise Refusal("approval receipt skills do not exactly match requested additions")
 if not isinstance(commit,str) or not SHA.fullmatch(commit) or not _valid_datetime(approval.get("approved_at")): raise Refusal("approval receipt commit/time is invalid")
 _run(["git","merge-base","--is-ancestor",commit,"HEAD"],ROOT)
 committed_manifest=_git_json(commit,Path("skills/packs.json"),"manifest"); _canonical_manifest(committed_manifest)
 proposal_path=Path("skills/proposals")/f"{proposal_id}.json"; _tracked_clean(proposal_path)
 proposal=_git_json(commit,proposal_path,"proposal"); _validate_proposal(proposal,proposal_id,profile,requested,catalog)
 if committed_manifest["profiles"][profile]!=current["profiles"][profile] or committed_manifest["approved_additions"][profile]!=current["approved_additions"][profile] or set(committed_manifest["approved_additions"][profile])!=requested: raise Refusal("current profile assignment/additions differ from approved committed state")

def _check_no_symlink(path:Path)->None:
 current=path
 while True:
  if current.is_symlink(): raise Refusal(f"profile home path contains a symlink: {current}")
  if current==current.parent: break
  current=current.parent

def main()->int:
 parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--profile",required=True,choices=sorted(PROFILE_MAP)); parser.add_argument("--nixkit",type=Path,default=Path.home()/"src/nixkit"); parser.add_argument("--skill",action="append",default=[]); parser.add_argument("--approval",type=Path); parser.add_argument("--apply",action="store_true"); args=parser.parse_args()
 try:
  manifest=_load_json(CANONICAL_MANIFEST,"canonical pack manifest"); _canonical_manifest(manifest)
  checkout=args.nixkit.expanduser().absolute()
  if checkout.is_symlink() or not checkout.is_dir(): raise Refusal("NixKit checkout must be an existing non-symlink directory")
  if _run(["git","rev-parse","HEAD"],checkout)!=NIXKIT_COMMIT: raise Refusal(f"NixKit HEAD does not match pinned commit {NIXKIT_COMMIT}")
  if _run(["git","status","--porcelain","--untracked-files=all"],checkout): raise Refusal("NixKit checkout must be clean, including untracked files")
  sources=checkout/"sources.json"
  try: actual_hash=hashlib.sha256(sources.read_bytes()).hexdigest()
  except OSError as exc: raise Refusal(f"cannot read pinned NixKit sources.json: {exc}") from exc
  if actual_hash!=NIXKIT_SOURCES_SHA256: raise Refusal("NixKit sources.json content does not match the audited hash")
  catalog=_source_catalog(sources)
  installer=checkout/"install.mjs"
  if not installer.is_file() or installer.is_symlink(): raise Refusal("NixKit install.mjs is missing or a symlink")
  npx=shutil.which("npx")
  if npx is None or not os.access(npx,os.X_OK): raise Refusal("executable npx is required for the pinned Node runtime")
  baseline={skill for pack in manifest["profiles"][args.profile] for skill in manifest["packs"][pack]}; additions=set(args.skill)
  if len(args.skill)!=len(additions) or any(not SKILL.fullmatch(s) for s in additions): raise Refusal("invalid or duplicate requested skill name")
  declared=set(manifest["approved_additions"][args.profile])
  if additions:
   if additions!=declared or args.approval is None: raise Refusal("requested additions require exact canonical declaration and approval")
   _approval(args.approval.expanduser().absolute(),args.profile,manifest,additions,catalog)
  elif args.approval is not None or declared: raise Refusal("declared additions require matching --skill values and approval")
  if args.apply:
   if _run(["git","status","--porcelain","--untracked-files=all"],ROOT): raise Refusal("Nix OS repository must be clean, including untracked files, for apply")
   for relative in (Path("skills/packs.json"),Path("scripts/install-skills.py")): _tracked_clean(relative)
  hermes_home=Path(os.environ.get("HERMES_HOME",str(Path.home()/".hermes"))).expanduser().absolute(); profile_home=hermes_home if PROFILE_MAP[args.profile]=="default" else hermes_home/"profiles"/PROFILE_MAP[args.profile]; _check_no_symlink(profile_home)
  command=["npx","--yes",f"node@{NODE_RUNTIME}",str(installer),"--apply","--skills","--agent","hermes","--prefix",str(profile_home)]
  for skill in sorted(baseline|additions): command.extend(["--skill",skill])
  print(("APPLY" if args.apply else "PREVIEW")+f" profile={args.profile} home={profile_home}"); print("command:"," ".join(json.dumps(v) for v in command))
  if not args.apply:return 0
  profile_home.mkdir(parents=True,exist_ok=True); result=subprocess.run(command,cwd=checkout,check=False)
  if result.returncode: raise Refusal(f"NixKit refused installation (exit {result.returncode}); existing conflicts were preserved")
  print(f"Installed or preserved {len(baseline|additions)} audited skill(s) for {args.profile}."); return 0
 except Refusal as exc: print(f"Refusing: {exc}",file=sys.stderr); return 2

if __name__=="__main__": raise SystemExit(main())

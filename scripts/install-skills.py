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
import stat
import subprocess
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_MANIFEST = ROOT / "skills/packs.json"
PROFILE_MAP = {"lnx":"default","pulse":"pulse","algua":"algua","meabeclick":"meabeclick","meabeclickux":"meabeclickux","meabeclickeng":"meabeclickeng","meabeclickgrowth":"meabeclickgrowth"}
PROFILES = set(PROFILE_MAP)
NIXKIT_REPOSITORY = "https://github.com/its-nix/kit.git"
NIXKIT_COMMIT = "92338765a1cc942b2a20dda3f1e220d6be0225e1"
NIXKIT_SNAPSHOT_COMMIT = "da5f36fc4c470fa28ffdcab1a6c6aaa3750bded3"
NIXKIT_SOURCES_SHA256 = "6493103af689bdf4bae5455e1d901646fe079e51a69c53b6f5bcf57c62786d21"
NIXKIT_INSTALLER_SHA256 = "28826444de3e78455b399e3de18c0b1d79aff038f2432ecca1975fec1e5c82b8"
NIXKIT_LOCAL_TREES = {"skills/watch":"64685da3912a54d5f672c4bdce0e89b69b4cd6c8"}
NODE_RUNTIME = "24.22.1"
EXPECTED_PACKS = {
 "baseline-evidence":["verification-before-completion"],
 "orchestrator-control":["dispatching-parallel-agents","receiving-code-review","handoff"],
 "project-lead-core":["brainstorming","domain-modeling","to-spec","to-tickets","codebase-design","receiving-code-review","handoff"],
 "public-research":[],
 "engineering-delivery":["executing-plans","using-git-worktrees","finishing-a-development-branch","receiving-code-review","codebase-design"],
 "ux-design-review":["frontend-design"],
 "product-development":["lnx-grilling","lnx-grill-me","lnx-domain-modeling","lnx-grill-with-docs","lnx-to-spec","lnx-writing-for-agents","nix-idea-to-mvp","writing-plans","subagent-driven-development"],
}
EXPECTED_ASSIGNMENTS = {
 "lnx":["baseline-evidence","orchestrator-control"], "pulse":["baseline-evidence","project-lead-core","public-research"],
 "algua":["baseline-evidence","project-lead-core","public-research"], "meabeclick":["baseline-evidence","project-lead-core","public-research"],
 "meabeclickux":["baseline-evidence","ux-design-review"], "meabeclickeng":["baseline-evidence","engineering-delivery"],
 "meabeclickgrowth":["baseline-evidence","public-research"],
}
LEGACY_NIXKIT_SKILLS = {"using-superpowers","brainstorming","writing-plans","executing-plans","systematic-debugging","test-driven-development","verification-before-completion","requesting-code-review","receiving-code-review","using-git-worktrees","finishing-a-development-branch","subagent-driven-development","dispatching-parallel-agents","diagnosing-superpowers","setup-matt-pocock-skills","grill-with-docs","grilling","domain-modeling","to-spec","to-tickets","codebase-design","research","handoff","caveman","ponytail","frontend-design","web-design-guidelines","agent-browser","remotion-best-practices","auto-editor","auto-editor-effects","auto-editor-export","auto-editor-transcribe","obsidian-markdown","qmd","gws-shared","gws-drive","gws-docs","gws-drive-upload","gws-docs-write","find-docs"}
NIXKIT_SKILLS = LEGACY_NIXKIT_SKILLS | {"lnx-grilling","lnx-grill-me","lnx-domain-modeling","lnx-grill-with-docs","lnx-to-spec","lnx-writing-for-agents","nix-idea-to-mvp","watch"}
PACK_PROPOSALS = {("lnx","product-development"):"lnx-product-development-92338765"}
PRODUCT_DEVELOPMENT_SKILLS = EXPECTED_PACKS["product-development"]
APPROVAL_AUTHORITY_DISCORD_ID = "454290355320520714"
APPROVAL_CHANNEL_ID = "1563181903253737542"
PRODUCT_REQUEST_EVIDENCE = {"kind":"request/proposal","platform":"discord","author_id":APPROVAL_AUTHORITY_DISCORD_ID,"channel_id":APPROVAL_CHANNEL_ID,"message_id":"1563496182829948941","quote":"sync it","timestamp":"2026-10-24T10:15:38.341000+00:00"}
PRODUCT_PROPOSAL_COMMIT = "083d008d3a83cd178e1f79bf962967ae7054fc0e"
PRODUCT_PROPOSAL_SHA256 = "06db117e1d84486a50f7beaae32f83fc3540ca8fd01eb5dc7fcf0f9e62100288"
PRODUCT_APPROVAL_EVIDENCE = {"kind":"approval","platform":"discord","author_id":APPROVAL_AUTHORITY_DISCORD_ID,"channel_id":APPROVAL_CHANNEL_ID,"message_id":"1563556252829622396","quote":f"approve {PACK_PROPOSALS[('lnx','product-development')]} at {PRODUCT_PROPOSAL_COMMIT}","timestamp":"2026-10-24T14:14:20.145000+00:00"}
HISTORICAL_APPROVAL_MANIFESTS = {
 "b7d9ba7ce3551e428b6f009c744ad3b71f821338": ("3f64702b483666b22468407d4e5c601911c6730f3f2bc182eacbfa2ca446feaa", ["caveman"]),
 "999cc615cd45c11b5ba10f9d02ff837171c68584": ("f143b7a554795331980742ebea23b39e61e13d8bbbd15321b653c28ab1082a30", ["caveman","watch"]),
}
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

def _run_bytes(command:list[str],cwd:Path)->bytes:
 result=subprocess.run(command,cwd=cwd,capture_output=True,check=False)
 if result.returncode:
  detail=result.stderr.decode("utf-8",errors="replace").strip() or result.stdout.decode("utf-8",errors="replace").strip() or str(result.returncode)
  raise Refusal(f"command failed: {' '.join(command)}: {detail}")
 return result.stdout

def _verify_local_tree(checkout:Path,relative:str,expected_tree:str)->None:
 """Require a local source payload to be exactly its pinned Git tree."""
 if _run(["git","rev-parse",f"{NIXKIT_COMMIT}:{relative}"],checkout)!=expected_tree:
  raise Refusal(f"pinned local source Git tree is not the audited object: {relative}")
 raw=_run_bytes(["git","ls-tree","-rz","-r","--full-tree",NIXKIT_COMMIT,"--",relative],checkout)
 expected:dict[str,tuple[str,str]]={}; prefix=relative+"/"
 for record in raw.split(b"\0"):
  if not record: continue
  try:
   header,path_bytes=record.split(b"\t",1); mode,kind,object_id=header.decode("ascii").split(" "); path=path_bytes.decode("utf-8")
  except (ValueError,UnicodeDecodeError) as exc: raise Refusal(f"cannot parse pinned local source Git tree: {relative}") from exc
  if kind!="blob" or mode not in {"100644","100755","120000"} or not path.startswith(prefix): raise Refusal(f"pinned local source Git tree has an unsupported entry: {path}")
  child=path[len(prefix):]
  if not child or child.startswith("/") or any(part in {"",".",".."} for part in child.split("/")) or child in expected: raise Refusal(f"pinned local source Git tree has an invalid path: {path}")
  expected[child]=(mode,object_id)
 if not expected: raise Refusal(f"pinned local source Git tree is empty: {relative}")
 expected_dirs={"/".join(parts[:index]) for child in expected for parts in [child.split("/")] for index in range(1,len(parts))}
 root=checkout/relative
 try:
  root_stat=root.lstat()
 except OSError as exc: raise Refusal(f"cannot inspect pinned local source payload {relative}: {exc}") from exc
 if not stat.S_ISDIR(root_stat.st_mode) or root.is_symlink(): raise Refusal(f"pinned local source payload is not a real directory: {relative}")
 actual:dict[str,os.stat_result]={}
 def walk(directory:Path,prefix_path:str="")->None:
  try: entries=list(os.scandir(directory))
  except OSError as exc: raise Refusal(f"cannot enumerate pinned local source payload {relative}: {exc}") from exc
  for entry in entries:
   child=f"{prefix_path}/{entry.name}" if prefix_path else entry.name
   try: info=entry.stat(follow_symlinks=False)
   except OSError as exc: raise Refusal(f"cannot inspect pinned local source entry {relative}/{child}: {exc}") from exc
   actual[child]=info
   if stat.S_ISDIR(info.st_mode): walk(Path(entry.path),child)
 walk(root)
 if set(actual)!=set(expected)|expected_dirs:
  raise Refusal(f"pinned local source payload file set differs from Git tree: {relative}")
 for directory in expected_dirs:
  if not stat.S_ISDIR(actual[directory].st_mode): raise Refusal(f"pinned local source entry type differs from Git tree: {relative}/{directory}")
 for child,(mode,object_id) in expected.items():
  path=root/child; info=actual[child]; expected_bytes=_run_bytes(["git","cat-file","blob",object_id],checkout)
  if mode=="120000":
   if not stat.S_ISLNK(info.st_mode): raise Refusal(f"pinned local source entry type differs from Git tree: {relative}/{child}")
   try: actual_bytes=os.fsencode(os.readlink(path))
   except OSError as exc: raise Refusal(f"cannot read pinned local source symlink {relative}/{child}: {exc}") from exc
  else:
   if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode): raise Refusal(f"pinned local source entry type differs from Git tree: {relative}/{child}")
   if bool(info.st_mode&0o111)!=(mode=="100755"): raise Refusal(f"pinned local source executable mode differs from Git tree: {relative}/{child}")
   try: actual_bytes=path.read_bytes()
   except OSError as exc: raise Refusal(f"cannot read pinned local source file {relative}/{child}: {exc}") from exc
  if actual_bytes!=expected_bytes: raise Refusal(f"pinned local source bytes differ from Git tree: {relative}/{child}")

def _verify_installer(checkout:Path)->Path:
 """Bind the executable installer bytes to the approved Git object and digest."""
 installer=checkout/"install.mjs"
 try: info=installer.lstat(); actual=installer.read_bytes()
 except OSError as exc: raise Refusal(f"cannot read pinned NixKit install.mjs: {exc}") from exc
 if not stat.S_ISREG(info.st_mode) or installer.is_symlink(): raise Refusal("NixKit install.mjs is missing or a symlink")
 expected=_run_bytes(["git","show",f"{NIXKIT_COMMIT}:install.mjs"],checkout)
 if actual!=expected or hashlib.sha256(actual).hexdigest()!=NIXKIT_INSTALLER_SHA256:
  raise Refusal("NixKit install.mjs bytes do not match the pinned reviewed Git object")
 return installer

def _load_json(path:Path,label:str)->dict:
 try: value=json.loads(path.read_text(encoding="utf-8"))
 except (OSError,UnicodeError,json.JSONDecodeError) as exc: raise Refusal(f"cannot read {label}: {exc}") from exc
 if not isinstance(value,dict): raise Refusal(f"{label} root must be an object")
 return value

def _source_catalog(path:Path)->dict[str,tuple[str,str,str|None]]:
 try: value=json.loads(path.read_text(encoding="utf-8"))
 except (OSError,UnicodeError,json.JSONDecodeError) as exc: raise Refusal(f"cannot parse pinned NixKit sources.json: {exc}") from exc
 if not isinstance(value,list): raise Refusal("pinned NixKit sources.json root must be an array")
 catalog:dict[str,tuple[str,str,str|None]]={}; local_records=0
 for source in value:
  if not isinstance(source,dict): raise Refusal("pinned NixKit sources.json has an invalid source record")
  if set(source)=={"repo","ref","skills"} and isinstance(source.get("repo"),str) and REPOSITORY.fullmatch(source["repo"]) and isinstance(source.get("ref"),str) and SHA.fullmatch(source["ref"]) and isinstance(source.get("skills"),list):
   repository,revision,expected_path=source["repo"],source["ref"],None
  elif source=={"local":"skills","skills":["watch"]}:
   local_records+=1; repository,revision,expected_path="its-nix/kit",NIXKIT_COMMIT,"skills/watch"
  else: raise Refusal("pinned NixKit sources.json has an invalid discriminated source record")
  for skill in source["skills"]:
   if not isinstance(skill,str) or not SKILL.fullmatch(skill) or skill in catalog: raise Refusal("pinned NixKit sources.json skill names must be valid and globally unique")
   catalog[skill]=(repository,revision,expected_path)
 if local_records!=1: raise Refusal("pinned NixKit sources.json must contain exactly the audited local watch record")
 if set(catalog)!=NIXKIT_SKILLS: raise Refusal("pinned NixKit sources.json does not contain the exact audited skill catalog")
 return catalog

def _canonical_manifest(manifest:dict)->None:
 if set(manifest)!={"schema_version","nixkit","packs","profiles","proposed_pack_additions","approved_pack_additions","approved_additions","task_only","excluded","governance"} or manifest.get("schema_version")!=1: raise Refusal("canonical pack manifest has invalid fields")
 if manifest.get("nixkit")!={"repository":NIXKIT_REPOSITORY,"commit":NIXKIT_COMMIT,"sources_sha256":NIXKIT_SOURCES_SHA256,"node_runtime":NODE_RUNTIME}: raise Refusal("canonical manifest does not match compile-time NixKit pins")
 if manifest.get("packs")!=EXPECTED_PACKS or manifest.get("profiles")!=EXPECTED_ASSIGNMENTS: raise Refusal("canonical manifest does not match the exact seven-profile pack topology")
 additions=manifest.get("approved_additions")
 if not isinstance(additions,dict) or set(additions)!=set(PROFILE_MAP) or any(not isinstance(v,list) or len(v)!=len(set(v)) or any(not isinstance(x,str) or not SKILL.fullmatch(x) for x in v) for v in additions.values()): raise Refusal("canonical manifest has invalid approved additions topology")
 proposed=manifest.get("proposed_pack_additions"); approved=manifest.get("approved_pack_additions")
 if not isinstance(proposed,dict) or not isinstance(approved,dict): raise Refusal("canonical manifest pack additions must be profile maps")
 for label,values in (("proposed",proposed),("approved",approved)):
  if set(values)!=set(PROFILE_MAP) or any(not isinstance(v,list) or len(v)!=len(set(v)) or any(not isinstance(x,str) or x not in EXPECTED_PACKS for x in v) for v in values.values()): raise Refusal(f"canonical manifest has invalid {label} pack additions topology")
 if any(set(proposed[p]) & set(approved[p]) for p in PROFILES): raise Refusal("proposed and approved pack additions must be disjoint")
 if set(proposed["lnx"]) | set(approved["lnx"])!={"product-development"} or any(proposed[p] or approved[p] for p in PROFILES-{"lnx"}): raise Refusal("product-development must be exactly one pending or approved LNX pack addition")
 if any(pack in manifest["profiles"][profile] for profile in PROFILES for pack in proposed[profile]+approved[profile]): raise Refusal("pack additions must not be folded into baseline profile assignments")
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

def _git_bytes(commit:str,relative:Path,label:str)->bytes:
 result=subprocess.run(["git","show",f"{commit}:{relative.as_posix()}"],cwd=ROOT,capture_output=True,check=False)
 if result.returncode: raise Refusal(f"cannot load committed {label} at {commit}: {result.stderr.decode(errors='replace').strip() or result.returncode}")
 return result.stdout

def _valid_datetime(value:object)->bool:
 if not isinstance(value,str) or not RFC3339.fullmatch(value): return False
 try: parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
 except ValueError: return False
 return parsed.tzinfo is not None and parsed.utcoffset() is not None

def _valid_discord_evidence(value:object,request:bool)->bool:
 required={"kind","platform","author_id","channel_id","message_id","quote","timestamp"}
 if not isinstance(value,dict) or set(value)!=required or value.get("platform")!="discord" or value.get("kind")!=("request/proposal" if request else "approval"): return False
 if not all(isinstance(value.get(k),str) and re.fullmatch(r"[0-9]{17,20}",value[k]) for k in ("author_id","channel_id","message_id")): return False
 return isinstance(value.get("quote"),str) and 0<len(value["quote"])<=MAX_TEXT and _valid_datetime(value.get("timestamp"))

def _validate_pack_approval_evidence(value:object,proposal_id:str,proposal_git_commit:str)->None:
 if not _valid_discord_evidence(value,False): raise Refusal("pack approval evidence is malformed")
 assert isinstance(value,dict)
 if value["author_id"]!=APPROVAL_AUTHORITY_DISCORD_ID: raise Refusal("pack approval evidence author is not Lior's verified Discord user")
 if value["channel_id"]!=APPROVAL_CHANNEL_ID: raise Refusal("pack approval evidence is not from the proposal channel")
 expected_quote=f"approve {proposal_id} at {proposal_git_commit}"
 if value["quote"]!=expected_quote: raise Refusal(f"pack approval evidence quote must exactly equal {expected_quote!r}")
 if proposal_id==PACK_PROPOSALS[("lnx","product-development")] and (proposal_git_commit!=PRODUCT_PROPOSAL_COMMIT or value!=PRODUCT_APPROVAL_EVIDENCE): raise Refusal("product-development approval must match the exact verified Discord message ID, timestamp, and proposal commit")

def _validate_pack_proposal(p:dict,proposal_id:str,profile:str,pack:str,catalog:dict[str,tuple[str,str,str|None]])->None:
 required={"schema_version","proposal_id","profile","pack","ordered_skills","nixkit","request_evidence","status"}
 expected_nixkit={"repository":NIXKIT_REPOSITORY,"commit":NIXKIT_COMMIT,"snapshot_commit":NIXKIT_SNAPSHOT_COMMIT,"sources_sha256":NIXKIT_SOURCES_SHA256}
 if set(p)!=required or p.get("schema_version")!=1 or p.get("proposal_id")!=proposal_id or not PROPOSAL_ID.fullmatch(str(p.get("proposal_id",""))) or p.get("profile")!=profile or p.get("pack")!=pack or p.get("status")!="pending_approval": raise Refusal("committed pack proposal identity/status is invalid")
 skills=p.get("ordered_skills")
 if not isinstance(skills,list) or skills!=EXPECTED_PACKS[pack] or len(skills)!=len(set(skills)) or any(not isinstance(x,str) or not SKILL.fullmatch(x) for x in skills): raise Refusal("committed pack proposal ordered skills do not match the exact pack")
 if p.get("nixkit")!=expected_nixkit: raise Refusal("committed pack proposal does not bind the exact NixKit checkout, snapshot, and sources hash")
 if not _valid_discord_evidence(p.get("request_evidence"),True): raise Refusal("committed pack proposal request evidence is invalid")
 if proposal_id==PACK_PROPOSALS[("lnx","product-development")] and p["request_evidence"]!=PRODUCT_REQUEST_EVIDENCE: raise Refusal("product-development request/proposal evidence is not exact")
 if any(catalog.get(skill) is None or catalog[skill][:2]!=("its-nix/kit",NIXKIT_SNAPSHOT_COMMIT) for skill in PRODUCT_DEVELOPMENT_SKILLS[:7]): raise Refusal("product-development snapshot skills do not match the exact pinned source snapshot")

def _validate_declared_pack_proposals(manifest:dict,catalog:dict[str,tuple[str,str,str|None]])->None:
 expected_proposals={f"{PACK_PROPOSALS[(profile,pack)]}.json" for profile in PROFILES for pack in manifest["proposed_pack_additions"][profile]+manifest["approved_pack_additions"][profile]}
 proposal_root=ROOT/"skills/pack-proposals"
 if proposal_root.is_symlink() or not proposal_root.is_dir(): raise Refusal("skills/pack-proposals must be a real directory")
 try: proposal_entries=list(proposal_root.iterdir())
 except OSError as exc: raise Refusal(f"cannot enumerate skills/pack-proposals: {exc}") from exc
 if any(path.is_symlink() or not path.is_file() or path.suffix!=".json" for path in proposal_entries): raise Refusal("skills/pack-proposals contains an unsupported entry")
 actual_proposals={path.name for path in proposal_entries}
 if actual_proposals!=expected_proposals: raise Refusal("pack proposal files do not exactly match canonical manifest declarations")
 expected_receipts={f"{PACK_PROPOSALS[(profile,pack)]}.json" for profile in PROFILES for pack in manifest["approved_pack_additions"][profile]}
 approval_root=ROOT/"skills/pack-approvals"
 if approval_root.exists() and (approval_root.is_symlink() or not approval_root.is_dir()): raise Refusal("skills/pack-approvals must be a real directory")
 try: approval_entries=list(approval_root.iterdir()) if approval_root.is_dir() else []
 except OSError as exc: raise Refusal(f"cannot enumerate skills/pack-approvals: {exc}") from exc
 if any(path.is_symlink() or not path.is_file() or path.suffix!=".json" for path in approval_entries): raise Refusal("skills/pack-approvals contains an unsupported entry")
 actual_receipts={path.name for path in approval_entries}
 if actual_receipts!=expected_receipts: raise Refusal("skills/pack-approvals files do not exactly match approved pack declarations")
 for profile in PROFILES:
  for pack in manifest["proposed_pack_additions"][profile]+manifest["approved_pack_additions"][profile]:
   proposal_id=PACK_PROPOSALS.get((profile,pack))
   if proposal_id is None: raise Refusal("pack addition has no canonical proposal binding")
   relative=Path("skills/pack-proposals")/f"{proposal_id}.json"; _tracked_clean(relative)
   _validate_pack_proposal(_load_json(ROOT/relative,"pack proposal"),proposal_id,profile,pack,catalog)

def _pack_approval(profile:str,pack:str,current:dict,catalog:dict[str,tuple[str,str,str|None]])->None:
 proposal_id=PACK_PROPOSALS.get((profile,pack))
 if proposal_id is None: raise Refusal("approved pack has no canonical proposal binding")
 relative=Path("skills/pack-approvals")/f"{proposal_id}.json"; _tracked_clean(relative)
 receipt=_load_json(ROOT/relative,"pack approval receipt")
 required={"schema_version","proposal_id","proposal_git_commit","proposal_file_sha256","profile","pack","ordered_skills","nixkit","approved_by","approval_evidence"}
 expected_nixkit={"repository":NIXKIT_REPOSITORY,"commit":NIXKIT_COMMIT,"snapshot_commit":NIXKIT_SNAPSHOT_COMMIT,"sources_sha256":NIXKIT_SOURCES_SHA256}
 if set(receipt)!=required or receipt.get("schema_version")!=1 or receipt.get("proposal_id")!=proposal_id or receipt.get("profile")!=profile or receipt.get("pack")!=pack or receipt.get("ordered_skills")!=EXPECTED_PACKS[pack] or receipt.get("nixkit")!=expected_nixkit or receipt.get("approved_by")!="Lior": raise Refusal("malformed, forged, or misbound pack approval receipt")
 commit=receipt.get("proposal_git_commit"); digest=receipt.get("proposal_file_sha256")
 if not isinstance(commit,str) or not SHA.fullmatch(commit) or not isinstance(digest,str) or not re.fullmatch(r"[a-f0-9]{64}",digest): raise Refusal("pack approval proposal commit/hash is invalid")
 if proposal_id==PACK_PROPOSALS[("lnx","product-development")] and (commit!=PRODUCT_PROPOSAL_COMMIT or digest!=PRODUCT_PROPOSAL_SHA256): raise Refusal("product-development approval does not bind the exact canonical proposal commit and file hash")
 evidence=receipt.get("approval_evidence"); _validate_pack_approval_evidence(evidence,proposal_id,commit)
 assert isinstance(evidence,dict)
 if (evidence["channel_id"],evidence["message_id"])==(PRODUCT_REQUEST_EVIDENCE["channel_id"],PRODUCT_REQUEST_EVIDENCE["message_id"]) or datetime.fromisoformat(evidence["timestamp"].replace("Z","+00:00"))<=datetime.fromisoformat(PRODUCT_REQUEST_EVIDENCE["timestamp"].replace("Z","+00:00")): raise Refusal("pack approval evidence must be distinct from and later than request/proposal evidence")
 _run(["git","merge-base","--is-ancestor",commit,"HEAD"],ROOT)
 proposal_path=Path("skills/pack-proposals")/f"{proposal_id}.json"; raw=_git_bytes(commit,proposal_path,"pack proposal")
 if hashlib.sha256(raw).hexdigest()!=digest: raise Refusal("pack approval proposal file SHA-256 does not match committed bytes")
 try: proposal=json.loads(raw)
 except json.JSONDecodeError as exc: raise Refusal(f"committed pack proposal is invalid JSON: {exc}") from exc
 if not isinstance(proposal,dict): raise Refusal("committed pack proposal must be an object")
 _validate_pack_proposal(proposal,proposal_id,profile,pack,catalog)
 committed_manifest=_git_json(commit,Path("skills/packs.json"),"manifest"); _canonical_manifest(committed_manifest)
 if pack not in committed_manifest["proposed_pack_additions"][profile] or pack in committed_manifest["approved_pack_additions"][profile]: raise Refusal("proposal commit must contain the pending, unapproved pack state")
 if pack not in current["approved_pack_additions"][profile] or pack in current["proposed_pack_additions"][profile]: raise Refusal("current manifest does not contain the exact approved pack state")

def _validate_proposal(p:dict,proposal_id:str,profile:str,skills:set[str],catalog:dict[str,tuple[str,str,str|None]])->None:
 required={"schema_version","proposal_id","profile","name","summary","rationale","source_url","repository","skill_path","revision","license","evidence_urls","risks","score_components","score","gates","gate_evidence","status"}
 if set(p)!=required or p.get("schema_version")!=1 or not isinstance(p.get("proposal_id"),str) or not PROPOSAL_ID.fullmatch(p["proposal_id"]) or p.get("proposal_id")!=proposal_id or p.get("profile") not in PROFILES or p.get("profile")!=profile or p.get("status")!="candidate" or not isinstance(p.get("name"),str) or not SKILL.fullmatch(p["name"]) or {p["name"]}!=skills: raise Refusal("committed proposal identity/status/skills do not match approval")
 if not isinstance(p.get("repository"),str) or not REPOSITORY.fullmatch(p["repository"]) or not isinstance(p.get("skill_path"),str) or not SKILL_PATH.fullmatch(p["skill_path"]) or not SHA.fullmatch(str(p.get("revision",""))): raise Refusal("committed proposal repository/path/revision is invalid")
 identity=catalog.get(p["name"])
 historical_watch=(proposal_id=="lnx-watch-a9cb5b57" and p["name"]=="watch" and p["repository"]=="its-nix/kit" and p["revision"]=="a9cb5b576097301ee63485649d5703db7479ad8f" and identity==("its-nix/kit",NIXKIT_COMMIT,"skills/watch"))
 if identity is None or (identity[:2]!=(p["repository"],p["revision"]) and not historical_watch): raise Refusal("approved skill does not uniquely belong to the proposal repository and pinned revision")
 if identity[2] is not None and p["skill_path"]!=identity[2]: raise Refusal("approved local skill does not match its exact audited repository path")
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

def _approval(path:Path,profile:str,current:dict,requested:set[str],catalog:dict[str,tuple[str,str,str|None]])->set[str]:
 for governance_file in (Path("skills/packs.json"), Path("scripts/install-skills.py")): _tracked_clean(governance_file)
 try: relative=path.resolve(strict=True).relative_to(ROOT.resolve())
 except (OSError,ValueError) as exc: raise Refusal("approval receipt must be a canonical path inside this repository") from exc
 _tracked_clean(relative)
 approval=_load_json(path,"approval receipt"); required={"schema_version","proposal_id","profile","skills","approved_by","approved_at","manifest_commit"}
 if set(approval)!=required or approval.get("schema_version")!=1 or approval.get("profile")!=profile or approval.get("approved_by")!="Lior": raise Refusal("malformed or misbound approval receipt")
 proposal_id=approval.get("proposal_id")
 if not isinstance(proposal_id,str) or not PROPOSAL_ID.fullmatch(proposal_id) or relative!=Path("skills/approvals")/f"{proposal_id}.json": raise Refusal("approval receipt is not at its canonical proposal-bound path")
 skills=approval.get("skills"); commit=approval.get("manifest_commit")
 approved=set(skills) if isinstance(skills,list) else set()
 if not isinstance(skills,list) or not approved<=requested or len(skills)!=len(approved) or not skills or any(not isinstance(x,str) or not SKILL.fullmatch(x) for x in skills): raise Refusal("approval receipt skills must be a nonempty exact subset of requested additions")
 if not isinstance(commit,str) or not SHA.fullmatch(commit) or not _valid_datetime(approval.get("approved_at")): raise Refusal("approval receipt commit/time is invalid")
 _run(["git","merge-base","--is-ancestor",commit,"HEAD"],ROOT)
 committed_manifest=_git_json(commit,Path("skills/packs.json"),"manifest")
 if commit in HISTORICAL_APPROVAL_MANIFESTS:
  expected_hash,expected_additions=HISTORICAL_APPROVAL_MANIFESTS[commit]
  historical_hash=hashlib.sha256(_git_bytes(commit,Path("skills/packs.json"),"historical approval manifest")).hexdigest()
  if historical_hash!=expected_hash or committed_manifest.get("profiles")!=EXPECTED_ASSIGNMENTS or committed_manifest.get("approved_additions",{}).get("lnx")!=expected_additions: raise Refusal("historical approval manifest no longer matches its exact reviewed bytes and state")
 else: _canonical_manifest(committed_manifest)
 proposal_path=Path("skills/proposals")/f"{proposal_id}.json"; _tracked_clean(proposal_path)
 proposal=_git_json(commit,proposal_path,"proposal"); _validate_proposal(proposal,proposal_id,profile,approved,catalog)
 if committed_manifest["profiles"][profile]!=current["profiles"][profile] or not approved<=set(committed_manifest["approved_additions"][profile]) or not approved<=set(current["approved_additions"][profile]): raise Refusal("approved scope is absent from the committed or current profile assignment/additions")
 return approved

def _check_no_symlink(path:Path)->None:
 current=path
 while True:
  if current.is_symlink(): raise Refusal(f"profile home path contains a symlink: {current}")
  if current==current.parent: break
  current=current.parent

def _frontmatter_name(path:Path)->str:
 try: text=path.read_text(encoding="utf-8")
 except (OSError,UnicodeError) as exc: raise Refusal(f"cannot read installed skill frontmatter {path}: {exc}") from exc
 lines=text.splitlines()
 if not lines or lines[0].strip()!="---": raise Refusal(f"installed skill has no validated YAML frontmatter: {path}")
 try: end=next(i for i,line in enumerate(lines[1:201],1) if line.strip()=="---")
 except StopIteration as exc: raise Refusal(f"installed skill frontmatter is unterminated: {path}") from exc
 matches=[]
 for line in lines[1:end]:
  match=re.fullmatch(r"\s*name\s*:\s*(['\"]?)([a-z0-9]+(?:-[a-z0-9]+)*)\1\s*(?:#.*)?",line)
  if match: matches.append(match.group(2))
 if len(matches)!=1 or not SKILL.fullmatch(matches[0]): raise Refusal(f"installed skill frontmatter must contain exactly one validated name: {path}")
 return matches[0]

def _preflight_duplicate_names(profile_home:Path,selected:set[str])->None:
 skill_root=profile_home/"skills"
 if skill_root.is_symlink(): raise Refusal("profile skills path must be a real non-symlink directory")
 if not skill_root.exists(): return
 if not skill_root.is_dir(): raise Refusal("profile skills path must be a real non-symlink directory")
 inventory:dict[str,list[Path]]={}
 paths:list[Path]=[]; pending=[skill_root]
 while pending:
  directory=pending.pop()
  try: entries=sorted(directory.iterdir())
  except OSError as exc: raise Refusal(f"cannot inventory profile skills recursively: {exc}") from exc
  for entry in entries:
   if entry.is_symlink(): raise Refusal(f"profile skills tree must not contain symlinks: {entry}")
   if entry.is_dir(): pending.append(entry)
   elif entry.name=="SKILL.md": paths.append(entry)
 for path in paths:
  if not path.is_file(): raise Refusal(f"installed skill manifest must be a regular non-symlink file: {path}")
  name=_frontmatter_name(path); inventory.setdefault(name,[]).append(path)
 for name in sorted(selected):
  found=inventory.get(name,[]); canonical=skill_root/name/"SKILL.md"
  if len(found)>1 or any(path!=canonical for path in found):
   locations=", ".join(str(path) for path in found)
   raise Refusal(f"selected skill name {name} already exists outside its sole canonical destination: {locations}")

def main()->int:
 parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--profile",required=True,choices=sorted(PROFILE_MAP)); parser.add_argument("--nixkit",type=Path,default=Path.home()/"src/nixkit"); parser.add_argument("--skill",action="append",default=[]); parser.add_argument("--approval",type=Path,action="append",default=[]); parser.add_argument("--apply",action="store_true"); args=parser.parse_args()
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
  local_paths={identity[2] for identity in catalog.values() if identity[2] is not None}
  if local_paths!=set(NIXKIT_LOCAL_TREES): raise Refusal("pinned NixKit local source paths do not match the audited tree set")
  for relative,tree in NIXKIT_LOCAL_TREES.items(): _verify_local_tree(checkout,relative,tree)
  _validate_declared_pack_proposals(manifest,catalog)
  for approved_profile in PROFILES:
   for approved_pack in manifest["approved_pack_additions"][approved_profile]: _pack_approval(approved_profile,approved_pack,manifest,catalog)
  installer=_verify_installer(checkout)
  npx=shutil.which("npx")
  if npx is None or not os.access(npx,os.X_OK): raise Refusal("executable npx is required for the pinned Node runtime")
  effective_packs=manifest["profiles"][args.profile]+manifest["approved_pack_additions"][args.profile]
  baseline={skill for pack in effective_packs for skill in manifest["packs"][pack]}; additions=set(args.skill)
  if len(args.skill)!=len(additions) or any(not SKILL.fullmatch(s) for s in additions): raise Refusal("invalid or duplicate requested skill name")
  declared=set(manifest["approved_additions"][args.profile])
  if additions:
   if additions!=declared or not args.approval: raise Refusal("requested additions require exact canonical declaration and approval coverage")
   covered:set[str]=set()
   for approval_path in args.approval:
    approved=_approval(approval_path.expanduser().absolute(),args.profile,manifest,additions,catalog)
    if covered&approved: raise Refusal("approval receipt scopes must be disjoint")
    covered|=approved
   if covered!=additions: raise Refusal("approval receipts do not exactly cover requested additions")
  elif args.approval or declared: raise Refusal("declared additions require matching --skill values and approval")
  if args.apply:
   if _run(["git","status","--porcelain","--untracked-files=all"],ROOT): raise Refusal("Nix OS repository must be clean, including untracked files, for apply")
   for relative in (Path("skills/packs.json"),Path("scripts/install-skills.py")): _tracked_clean(relative)
  hermes_home=Path(os.environ.get("HERMES_HOME",str(Path.home()/".hermes"))).expanduser().absolute(); profile_home=hermes_home if PROFILE_MAP[args.profile]=="default" else hermes_home/"profiles"/PROFILE_MAP[args.profile]; _check_no_symlink(profile_home)
  _preflight_duplicate_names(profile_home,baseline|additions)
  command=[npx,"--yes",f"node@{NODE_RUNTIME}",str(installer),"--apply","--skills","--agent","hermes","--prefix",str(profile_home)]
  for skill in sorted(baseline|additions): command.extend(["--skill",skill])
  print(("APPLY" if args.apply else "PREVIEW")+f" profile={args.profile} home={profile_home}"); print("command:"," ".join(json.dumps(v) for v in command))
  if not args.apply:return 0
  _verify_installer(checkout)
  for relative,tree in NIXKIT_LOCAL_TREES.items(): _verify_local_tree(checkout,relative,tree)
  profile_home.mkdir(parents=True,exist_ok=True); result=subprocess.run(command,cwd=checkout,check=False)
  if result.returncode: raise Refusal(f"NixKit refused installation (exit {result.returncode}); existing conflicts were preserved")
  print(f"Installed or preserved {len(baseline|additions)} audited skill(s) for {args.profile}."); return 0
 except Refusal as exc: print(f"Refusing: {exc}",file=sys.stderr); return 2

if __name__=="__main__": raise SystemExit(main())

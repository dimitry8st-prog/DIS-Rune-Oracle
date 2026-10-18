"""Validate tar paths/types/size before extraction; never extract .git or links."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile


def inspect(archive, destination=None):
    archive=Path(archive)
    with tarfile.open(archive) as source:
        members=source.getmembers();seen=set();inventory=[]
        if len(members)>2000 or sum(m.size for m in members)>20_000_000:
            raise ValueError('archive exceeds size/count bound')
        for member in members:
            path=PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or '\\' in member.name or '\x00' in member.name:
                raise ValueError('unsafe path: '+member.name)
            if member.type not in (tarfile.REGTYPE,tarfile.AREGTYPE,tarfile.DIRTYPE):
                raise ValueError('links/special files are forbidden: '+member.name)
            if str(path) in seen:raise ValueError('duplicate path: '+member.name)
            seen.add(str(path))
            if member.size>4_000_000:raise ValueError('member too large')
            if member.isfile():
                raw=source.extractfile(member).read()
                inventory.append({'path':str(path),'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
                                  'git_metadata_excluded':'.git' in path.parts})
        if destination is not None:
            root=Path(destination)
            root.mkdir(parents=True,exist_ok=False)  # no pre-existing files or symlinks
            for member in members:
                path=PurePosixPath(member.name)
                if member.isfile() and '.git' not in path.parts:
                    target=root.joinpath(*path.parts);target.parent.mkdir(parents=True,exist_ok=True)
                    with target.open('xb') as output:output.write(source.extractfile(member).read())
    return {'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':inventory}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive');parser.add_argument('--extract-to')
    args=parser.parse_args()
    print(json.dumps(inspect(args.archive,args.extract_to),ensure_ascii=False,indent=2))

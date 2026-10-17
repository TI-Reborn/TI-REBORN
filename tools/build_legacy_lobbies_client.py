"""Compose the two verified native transformations into one reviewed release."""
from pathlib import Path
import hashlib
import json

from deploy import client_team_lobby_availability as lobby
from deploy import client_texture_quality as texture
from tools import publish_legacy_lobbies_client as release


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    folder = release.FOLDER
    source = (folder/'client/source/silver.dll').read_bytes()
    ti = (folder/'client/source/ti.exe').read_bytes()
    intermediate = lobby.patch(source)
    candidate = texture.patch(intermediate,expected_sha=sha(intermediate),ti=ti)
    declared = []
    for review in (lobby.review(source,intermediate),texture.review(intermediate,candidate)):
        for row in review['changes']:
            declared.append((row['offset'],row['offset']+row['size'],row['purpose']))
    merged = []
    for start,end,purpose in sorted(declared):
        if merged and start<=merged[-1][1]:
            previous = merged.pop()
            merged.append((previous[0],max(previous[1],end),previous[2]))
        else:
            merged.append((start,end,purpose))
    review = dict(changes=[dict(offset=start,size=end-start,
                  source_sha256=sha(source[start:end]),candidate_sha256=sha(candidate[start:end]),
                  purpose=purpose) for start,end,purpose in merged],
                  appended_size=len(candidate)-len(source),
                  appended_sha256=sha(candidate[len(source):]))
    preserved = release.PUBLISHER.native_preserved(source,candidate,review)
    built = (folder/'textures/candidate-final/silver.dll').read_bytes()
    if candidate != built:
        raise ValueError('Combined candidate differs from tested texture build')
    sampler = json.loads((folder/'textures/candidate-final/native-sampler-proof.json').read_text())
    if sampler.get('candidate_sha256') != sha(candidate):
        raise ValueError('Native sampler proof is for another candidate')
    package = dict(schema=1,previous_version=release.PREVIOUS_VERSION,version=release.VERSION,
                   baseline_manifest_sha256=release.MANIFEST_SHA,selection=dict(fix=release.FIX),
                   native_review=review,files=[dict(path='silver.dll',source='silver.dll',
                         sha256=sha(candidate),size=len(candidate),kind='native')])
    client = folder/'client'
    for name,raw in (('silver.dll',candidate),('package.json',(json.dumps(package,indent=2)+'\n').encode())):
        with (client/name).open('xb') as out:
            out.write(raw)
    proof = dict(passed=True,source_sha256=sha(source),availability_sha256=sha(intermediate),
                 candidate_sha256=sha(candidate),candidate_bytes=len(candidate),
                 package_sha256=sha((client/'package.json').read_bytes()),preservation=preserved,
                 source_code_sha256={str(Path(m.__file__).relative_to(release.ROOT)):sha(Path(m.__file__).read_bytes())
                                     for m in (lobby,texture)},graphical_acceptance=False)
    with (client/'composition.json').open('x',encoding='utf-8') as out:
        json.dump(proof,out,indent=2)
    print(json.dumps(proof,indent=2))


if __name__ == '__main__':
    main()

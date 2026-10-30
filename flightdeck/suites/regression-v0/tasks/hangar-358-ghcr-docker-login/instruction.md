`hangar images build` decides whether each harness pack already exists by asking its registry for the tag's digest.
For ghcr.io it asks for a pull token anonymously. The release's packages are private, so ghcr.io answers 403, every
pack reads as "unknown" (`RegistryError ... refused a pull token`), nothing is built and the release job exits 1.

For registries other than Artifact Registry and gcr.io, use the credentials `docker login` saved in
`$DOCKER_CONFIG/config.json` (the `auths` entry for the registry host, keyed either `ghcr.io` or `https://ghcr.io`)
when asking the registry's token endpoint. Without a login the behaviour stays as it is (anonymous, refused). With
one, a private package reads as present or missing (`Registry.digest` returns `None` for a missing tag). Google's
registries are unchanged, and credentials must go only to the registry's own token endpoint, never to a realm on
another host. The code is in `src/hangar/registry.py`; see `tests/test_images.py`.

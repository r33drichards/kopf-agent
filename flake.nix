{
  description = "Kopf Agent Docker Image";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.05";
    flake-utils.url = "github:numtide/flake-utils";
    poetry2nix.url = "github:nix-community/poetry2nix";
  };

  outputs = { self, nixpkgs, flake-utils, poetry2nix, ... }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
        lib = pkgs.lib;
        pythonEnv = pkgs.python311.withPackages (ps: with ps; [ pip kopf kubernetes python-dotenv ]);
        entrypoint = pkgs.writeScript "entrypoint.sh" ''
          #!${pkgs.bash}/bin/bash
          exec ${pythonEnv}/bin/python -m kopf run ${./main.py} --verbose "$@"
        '';
      in {
        packages.dockerImage = pkgs.dockerTools.streamLayeredImage {
          name = "kopf-agent";
          tag = "latest";
          maxLayers = 120;

          contents = [ pythonEnv pkgs.fakeNss ];
          config = {
            Entrypoint = [ "${entrypoint}" ];
            WorkingDir = "/app";
            Env = [ "PYTHONUNBUFFERED=1"  ];
          };
        };
        defaultPackage = self.packages.${system}.dockerImage;
      }
    );
}
function resultsStruct = run_all_scenarios(P, scenarios)
%RUN_ALL_SCENARIOS  Run all scenario configs and return a struct array.

nSc = numel(scenarios);
resultsStruct(nSc) = struct();

for k = 1:nSc
    S = scenarios(k);
    fprintf('Running %s\n', S.name);
    out = run_scenario_1D(P, S.type, S.bcType, S.hLevel, S.T_env);
    resultsStruct(k).name    = S.name;
    resultsStruct(k).type    = S.type;
    resultsStruct(k).bcType  = S.bcType;
    resultsStruct(k).hLevel  = S.hLevel;
    resultsStruct(k).outputs = out;
end
end
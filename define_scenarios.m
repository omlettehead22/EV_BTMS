function scenarios = define_scenarios(P)
%DEFINE_SCENARIOS  Return an array of scenario configs.

scenarios(1).name   = 'drive-air-mid';
scenarios(1).type   = 'drive';
scenarios(1).bcType = 'air';
scenarios(1).hLevel = 'mid';
scenarios(1).T_env  = P.T_amb_mild;

scenarios(2).name   = 'drive-liquid-low';
scenarios(2).type   = 'drive';
scenarios(2).bcType = 'liquid';
scenarios(2).hLevel = 'low';
scenarios(2).T_env  = P.T_coolant;

scenarios(3).name   = 'charge-air-high';
scenarios(3).type   = 'charge';
scenarios(3).bcType = 'air';
scenarios(3).hLevel = 'high';
scenarios(3).T_env  = P.T_amb_mild;

scenarios(4).name   = 'charge-liquid-mid';
scenarios(4).type   = 'charge';
scenarios(4).bcType = 'liquid';
scenarios(4).hLevel = 'mid';
scenarios(4).T_env  = P.T_coolant;
end
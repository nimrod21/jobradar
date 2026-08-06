-- Work mode (remote / hybrid / onsite) is orthogonal to geography.
-- Location modes become: any | region | country | place.

alter table trackers add column work_modes text[] not null default '{}';

-- old 'remote' location mode -> a work-mode toggle, location freed up
update trackers set work_modes = array['remote'], location_mode = 'any'
where location_mode = 'remote';

-- old free-text mode renamed
update trackers set location_mode = 'place' where location_mode = 'text';

-- 'georgia' was a region preset; it is a country
update trackers set location_mode = 'country', location_value = 'Georgia'
where location_mode = 'region' and location_value = 'georgia';
